# Semblance, explained without a coding background

Semblance answers two questions: **“Does this recipient look like an impersonator?”** and **“What happened in this wallet that deserves a closer look?”** It watches public information. It never controls a wallet.

## What someone can do

1. **Check before sending.** Paste the destination and compare it with a known address, a saved contact, or prior native-currency recipients. Semblance highlights exactly which characters differ. It warns about lookalikes without treating an exact match as proof the recipient is safe.
2. **Monitor.** Add a public wallet address. Semblance retrieves activity and looks for a sender impersonating a prior recipient, or a token permission allowing unusually broad spending. Every warning has evidence and a suggested next action.
3. **Replay.** Step through a simulated incident showing how the pattern develops. Recruiters can inspect the product without owning crypto or connecting a wallet.

## How the pieces fit together

Think of a small security desk with a screen, an analyst, a filing cabinet and a scheduled patrol.

```mermaid
flowchart TD
    Browser[Your browser: Check / Monitor / Replay] --> Service[Python service: validate requests and compare addresses]
    Service <--> Database[(Neon database: watchlists, history, alerts)]
    Timer[Cloudflare timer: every five minutes] --> Collector[Collector: read new activity and apply rules]
    Collector <--> Alchemy[Alchemy: access to public Base blockchain data]
    Collector --> Database
    Database --> Service
    Service --> Browser
```

**The website** is built with React (a library for interactive screens) and TypeScript (JavaScript with checks that catch inconsistent data types). It draws the forms, highlighted addresses, history and replay. Vercel hosts it at a free web address.

**The service** is written in Python using FastAPI (a framework for accepting structured requests from the website). Its API (the agreed request-and-response interface) validates what the visitor enters, controls access to that visitor's saved list, performs comparisons and returns the evidence.

**The database** is PostgreSQL (a structured storage system) hosted by Neon. It remembers contacts, watchlists, observed transfers, alerts and the last processed block. A block is a numbered batch of blockchain activity. A cursor is the bookmark saying where collection stopped.

**The collector** is the background patrol. A Cloudflare cron trigger (a scheduled timer) wakes it even if nobody has the website open. It reads the next range, runs the rules and saves the findings. It saves its bookmark only if the whole range succeeded. If a provider fails, it keeps the old findings and shows a failure or stale status, rather than implying the wallet is clear.

**Alchemy** supplies access to Base's public data. Base is an Ethereum layer-2 network (a network that executes transactions while relying on Ethereum for settlement). We use indexed transfer history and separate approval-event queries; one feed does not provide everything.

## What detection actually means

**Lookalike addresses:** an attacker may use an address with the same beginning and ending as someone you recognize. The rule compares the whole address and highlights differences. Monitoring only uses earlier positive native transfers to establish recipient history, so random inbound activity and token-generated events cannot silently become trusted references.

**Unlimited approvals:** a token approval gives a contract permission to spend that token from a wallet. Maximum approval can be intentional, but creates exposure worth reviewing. Semblance checks what the token contract reported at the observed block and shows whether that read confirmed maximum permission, a lower permission, or failed. It does not label every permission a scam or claim it is still active now.

The rules are deterministic (the same evidence produces the same result), so we can test and explain them. An AI model is not deciding whether a transaction is safe. Coding assistants help build the product; they are not required to run each check.

## Why the design is useful

- **Preventive:** the recipient comparison can warn before a user sends. It cannot intercept or block the actual transaction.
- **Explainable:** users can inspect the full address, transaction and token contract behind a warning.
- **Recoverable:** repeated reads do not create duplicate alerts, and changed blockchain snapshots are rejected or rebuilt.
- **Private by default:** each browser has its own saved list and contact labels. No password, wallet connection or signature is needed. Clearing the browser's session cookie loses access to that list.
- **Free pilot:** three unique monitored wallets across the installation, with checks targeted every five minutes. The website refreshes its stored results more often. Provider delays and free quotas can increase delay or pause service. Manual comparisons and replay do not require a blockchain read.

## What the first release does not claim

It is not a universal scam detector, a complete audit of every existing token permission, or a replacement for a wallet. It does not cover NFT permissions or internal contract movements. The replay is simulated. Passing tests establishes the tested behavior, not a real-world detection-accuracy percentage.

No domain purchase is necessary. A custom domain can be added later without changing this architecture.
