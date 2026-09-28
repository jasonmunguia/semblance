import asyncio
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text

from .config import Settings, get_settings
from .db import Acknowledgement, Alert, BrowserSession, Contact, Monitor, Transfer, Watch, database
from .demo import COVERAGE, RECIPIENT, example_state
from .domain import check_recipient, normalize_address
from .references import reference_kind


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


class AddressInput(BaseModel):
    address: str = Field(max_length=100)
    label: str = Field(default="", max_length=60)


class CheckInput(BaseModel):
    destination: str = Field(max_length=100)
    wallet_id: str | None = Field(default=None, max_length=100)
    reference_addresses: list[str] = Field(default_factory=list, max_length=20)
    demo: bool = False


def create_app(settings: Settings | None = None):
    settings = settings or get_settings()
    settings.validate_deployment()
    engine, session_factory = database(settings.database_url)
    signer = URLSafeTimedSerializer(settings.session_secret, salt="semblance-browser")
    rates = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="Semblance", lifespan=lifespan)
    app.state.sessions = session_factory
    app.state.settings = settings

    @app.middleware("http")
    async def browser_session(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if origin and urlsplit(origin).netloc != request.headers.get("host"):
                    return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)
                if request.headers.get("sec-fetch-site") == "cross-site":
                    return JSONResponse({"detail": "Cross-site request is not allowed"}, status_code=403)
                if request.url.path in ("/api/check", "/api/wallets", "/api/trusted") and request.method == "POST" and "application/json" not in request.headers.get("content-type", ""):
                    return JSONResponse({"detail": "Use application/json"}, status_code=415)
            # This process-local limiter is for a single API replica. Hosted mode adds platform protection.
            client = request.client.host if request.client else "unknown"
            now = time.time()
            bucket = rates[client]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= 120:
                return JSONResponse({"detail": "Too many requests; try again in a minute"}, status_code=429)
            bucket.append(now)
            if len(rates) > 10000:
                for key in list(rates):
                    if not rates[key] or rates[key][-1] < now - 60:
                        del rates[key]
            sid = None
            token = request.cookies.get("semblance_session")
            if token:
                try:
                    sid = signer.loads(token, max_age=settings.session_days * 86400)
                except (BadSignature, SignatureExpired):
                    pass
            sid = sid if isinstance(sid, str) and len(sid) == 36 else str(uuid.uuid4())
            with session_factory.begin() as db:
                browser = db.get(BrowserSession, sid)
                if browser is None:
                    db.add(BrowserSession(id=sid))
                else:
                    browser.touched = now
            request.state.session_id = sid
            response = await call_next(request)
            response.set_cookie("semblance_session", signer.dumps(sid), httponly=True,
                                secure=settings.production, samesite="lax", max_age=settings.session_days * 86400)
            response.headers["Cache-Control"] = "no-store"
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def address(value):
        try:
            return normalize_address(value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def watch_data(watch, monitor):
        status = monitor.status
        if not settings.alchemy_key:
            status = "unavailable"
        elif monitor.last_checked and time.time() - monitor.last_checked > settings.poll_seconds * 3:
            status = "stale" if status not in ("error",) else status
        return {"id": watch.id, "address": watch.address, "label": watch.label, "status": status,
                "last_checked": iso(monitor.last_checked), "coverage_start": monitor.coverage_start,
                "cursor": monitor.cursor, "error": monitor.error, "history_partial": monitor.history_partial}

    @app.post("/internal/collect")
    async def collect(request: Request):
        if not settings.collector_secret or not secrets.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + settings.collector_secret
        ):
            raise HTTPException(401, "Unauthorized")
        if not settings.alchemy_key:
            raise HTTPException(503, "Live data provider is not configured")
        from .provider import BaseProvider
        from .worker import run_once
        provider = BaseProvider(settings.alchemy_key)
        try:
            return await asyncio.wait_for(run_once(session_factory, provider, settings),
                                          timeout=settings.collector_budget_seconds)
        except TimeoutError:
            return {"processed": None, "budget_reached": True}
        finally:
            await provider.aclose()

    @app.get("/health")
    def health():
        return {"status": "ok", "live_configured": bool(settings.alchemy_key)}

    @app.get("/api/demo")
    def demo():
        return example_state()

    @app.get("/api/state")
    def state(request: Request):
        sid = request.state.session_id
        with session_factory() as db:
            watches = db.scalars(select(Watch).where(Watch.session_id == sid)).all()
            watch_ids = {w.address: w.id for w in watches}
            transfers = db.scalars(select(Transfer).where(Transfer.address.in_(watch_ids)).order_by(Transfer.block.desc()).limit(200)).all()
            alerts = db.scalars(select(Alert).where(Alert.address.in_(watch_ids)).order_by(Alert.block.desc()).limit(100)).all()
            ack = set(db.scalars(select(Acknowledgement.alert_id).where(Acknowledgement.session_id == sid)).all())
            contacts = db.scalars(select(Contact).where(Contact.session_id == sid)).all()
            return {"mode": "live", "configured": bool(settings.alchemy_key), "coverage": COVERAGE,
                    "limits": {"max_wallets": settings.max_wallets, "max_global_wallets": settings.max_global_wallets, "poll_seconds": settings.poll_seconds},
                    "wallets": [watch_data(w, db.get(Monitor, w.address)) for w in watches],
                    "trusted": [{"id": c.id, "address": c.address, "label": c.label} for c in contacts],
                    "transfers": [{**t.data, "id": t.id, "wallet_id": watch_ids[t.address], "demo": False} for t in transfers],
                    "alerts": [{**a.data, "id": a.id, "wallet_id": watch_ids[a.address], "demo": False,
                                "acknowledged": a.id in ack} for a in alerts]}

    @app.post("/api/wallets", status_code=201)
    def add_wallet(data: AddressInput, request: Request):
        normalized, sid = address(data.address), request.state.session_id
        with session_factory.begin() as db:
            if engine.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(84530018)"))
            existing = db.scalar(select(Watch).where(Watch.session_id == sid, Watch.address == normalized))
            if existing:
                return watch_data(existing, db.get(Monitor, normalized))
            count = db.scalar(select(func.count()).select_from(Watch).where(Watch.session_id == sid))
            if count >= settings.max_wallets:
                raise HTTPException(409, "Your watchlist is full; remove a wallet first")
            monitor = db.get(Monitor, normalized)
            if monitor is None:
                if db.scalar(select(func.count()).select_from(Monitor)) >= settings.max_global_wallets:
                    raise HTTPException(409, "This pilot has reached its monitoring capacity; recipient checks still work")
                monitor = Monitor(address=normalized)
                db.add(monitor)
                db.flush()
            watch = Watch(session_id=sid, address=normalized, label=data.label.strip() or "Watched wallet")
            db.add(watch)
            db.flush()
            return watch_data(watch, monitor)

    def remove_owned(model, item_id, sid):
        with session_factory.begin() as db:
            if model is Watch and engine.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(84530018)"))
            row = db.get(model, item_id)
            if not row or row.session_id != sid:
                raise HTTPException(404, "Item not found")
            removed_address = row.address if model is Watch else None
            db.delete(row)
            db.flush()
            if removed_address and not db.scalar(select(Watch.id).where(Watch.address == removed_address)):
                db.execute(delete(Monitor).where(Monitor.address == removed_address))
        return {"ok": True}

    @app.delete("/api/wallets/{item_id}")
    def remove_wallet(item_id: str, request: Request):
        return remove_owned(Watch, item_id, request.state.session_id)

    @app.post("/api/trusted", status_code=201)
    def add_contact(data: AddressInput, request: Request):
        normalized, sid = address(data.address), request.state.session_id
        with session_factory.begin() as db:
            contact = db.scalar(select(Contact).where(Contact.session_id == sid, Contact.address == normalized))
            if contact is None:
                if db.scalar(select(func.count()).select_from(Contact).where(Contact.session_id == sid)) >= 50:
                    raise HTTPException(409, "Contact limit reached")
                contact = Contact(session_id=sid, address=normalized, label=data.label.strip() or "Trusted contact")
                db.add(contact)
                db.flush()
            return {"id": contact.id, "address": contact.address, "label": contact.label}

    @app.delete("/api/trusted/{item_id}")
    def remove_contact(item_id: str, request: Request):
        return remove_owned(Contact, item_id, request.state.session_id)

    @app.post("/api/alerts/{item_id}/acknowledge")
    def acknowledge(item_id: str, request: Request):
        sid = request.state.session_id
        with session_factory.begin() as db:
            alert = db.get(Alert, item_id)
            if not alert or not db.scalar(select(Watch).where(Watch.session_id == sid, Watch.address == alert.address)):
                raise HTTPException(404, "Alert not found")
            if not db.get(Acknowledgement, (sid, item_id)):
                db.add(Acknowledgement(session_id=sid, alert_id=item_id))
        return {"ok": True}

    @app.post("/api/check")
    def check(data: CheckInput, request: Request):
        destination = address(data.destination)
        refs = [{"address": address(r), "kind": "manual_reference", "label": "Your reference"} for r in data.reference_addresses]
        note = "Compared against your references. This check does not establish overall safety."
        if data.demo:
            refs = [{"address": RECIPIENT, "kind": "example", "label": "Example recipient"}]
            note = "Simulated example references only; no live blockchain check was performed."
        else:
            with session_factory() as db:
                refs.extend({"address": c.address, "kind": "trusted_contact", "label": c.label}
                            for c in db.scalars(select(Contact).where(Contact.session_id == request.state.session_id)))
                if data.wallet_id:
                    watch = db.get(Watch, data.wallet_id)
                    if not watch or watch.session_id != request.state.session_id:
                        raise HTTPException(404, "Wallet not found")
                    monitor = db.get(Monitor, watch.address)
                    for transfer in db.scalars(select(Transfer).where(Transfer.address == watch.address)):
                        t = transfer.data
                        kind = reference_kind(t, watch.address)
                        if kind:
                            refs.append({"address": t["to_address"], "kind": kind,
                                         "label": "Verified direct-token recipient" if kind == "verified_token_recipient" else "Previous native-transfer recipient"})
                    note = f"References use native payments and verified direct token payments. Token verification is bounded; routed and smart-wallet payments are excluded. History status: {watch_data(watch, monitor)['status']}; " + ("partial. " if monitor.history_partial else "bounded coverage. ") + "A match does not establish safety."
        return check_recipient(destination, refs, note)

    static = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if static.is_dir():
        @app.get("/", include_in_schema=False)
        @app.get("/index.html", include_in_schema=False)
        def website_index():
            # Deployment archives normalize mtimes; size-based static ETags can
            # otherwise reuse HTML pointing to a previous build's missing assets.
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-store"})

        app.mount("/", StaticFiles(directory=static, html=True), name="website")
    return app
