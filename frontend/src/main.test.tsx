// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from './main';

const demo = { mode:'demo', configured:false, coverage:[], limits:{max_wallets:3}, wallets:[], trusted:[], transfers:[], alerts:[] };
const live = {...demo,mode:'live'};
const warning = { status:'lookalike', matches:[{address:'0x7a2d98b145ac732bcb21e8d349c70f129ad2e6b4',kind:'example',label:'Example recipient',matching_prefix:4,matching_suffix:4,differing_indices:[6]}],checked_references:1,coverage_note:'Example only.',action:'Verify the full address.' };
const json=(value:unknown)=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
afterEach(()=>{cleanup();vi.unstubAllGlobals()});

describe('recipient comparison evidence',()=>{
  it('clears displayed address evidence when the destination changes',async()=>{
    vi.stubGlobal('fetch',vi.fn(async (input:string)=>json(input==='/api/check'?warning:demo)));
    render(<App/>);
    const input=await screen.findByLabelText('Destination address');
    fireEvent.change(input,{target:{value:'0x7a2d08b145ac732bcb21e8d349c70f129ad2e6b4'}});
    fireEvent.click(screen.getByRole('button',{name:/Compare addresses/}));
    expect(await screen.findByText('Possible lookalike')).toBeTruthy();
    fireEvent.change(input,{target:{value:'0x1111111111111111111111111111111111111111'}});
    expect(screen.queryByText('Possible lookalike')).toBeNull();
  });
  it('ignores an old comparison response after a reference edit',async()=>{
    let complete:(value:Response)=>void=()=>{};
    const pending=new Promise<Response>(resolve=>{complete=resolve});
    vi.stubGlobal('fetch',vi.fn(async (input:string)=>input==='/api/check'?pending:json(input==='/api/state'?live:demo)));
    render(<App/>);
    fireEvent.click(await screen.findByRole('button',{name:'Live'}));
    const destination=await screen.findByLabelText('Destination address');
    const reference=screen.getByLabelText(/Known address to compare/);
    fireEvent.change(destination,{target:{value:'0x7a2d08b145ac732bcb21e8d349c70f129ad2e6b4'}});
    fireEvent.change(reference,{target:{value:'0x7a2d98b145ac732bcb21e8d349c70f129ad2e6b4'}});
    fireEvent.click(screen.getByRole('button',{name:/Compare addresses/}));
    fireEvent.change(reference,{target:{value:'0x2222222222222222222222222222222222222222'}});
    complete(json(warning));
    await waitFor(()=>expect(screen.getByRole('button',{name:/Compare addresses/}).hasAttribute('disabled')).toBe(false));
    expect(screen.queryByText('Possible lookalike')).toBeNull();
  });
});

describe('state mode',()=>{
  it('does not let a delayed example response replace live state',async()=>{
    let complete:(value:Response)=>void=()=>{};
    const delayedDemo=new Promise<Response>(resolve=>{complete=resolve});
    vi.stubGlobal('fetch',vi.fn(async (input:string)=>input==='/api/demo'?delayedDemo:json(live)));
    render(<App/>);
    fireEvent.click(screen.getByRole('button',{name:'Live'}));
    expect(await screen.findByText('Live workspace · provider unavailable')).toBeTruthy();
    complete(json(demo));
    await waitFor(()=>expect(screen.queryByText('Simulated example')).toBeNull());
    expect(screen.getByRole('button',{name:'Live'}).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('token provenance',()=>{
  it('shows the full token contract and only links real Base activity',async()=>{
    const contract='0x3333333333333333333333333333333333333333';
    const transfer={id:'t1',wallet_id:'w1',tx_hash:'0xabc',block:1,timestamp:null,from_address:'0x1111111111111111111111111111111111111111',to_address:'0x2222222222222222222222222222222222222222',value:'50',asset:'USDC',category:'erc20',token_address:contract,demo:false};
    vi.stubGlobal('fetch',vi.fn(async (input:string)=>json(input==='/api/state'?{...live,transfers:[transfer]}:{...demo,transfers:[{...transfer,demo:true}]})));
    render(<App/>);
    fireEvent.click(await screen.findByRole('button',{name:'Monitor'}));
    expect(await screen.findByText('Token-reported name; verify contract')).toBeTruthy();
    expect(screen.getByText(contract).closest('a')).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'Live'}));
    const address=await screen.findByRole('link',{name:`View token contract ${contract} on Basescan`});
    expect(address.getAttribute('href')).toBe(`https://basescan.org/address/${contract}`);
    expect(screen.getByText('Timestamp unavailable')).toBeTruthy();
  });
});

describe('example and monitoring guidance',()=>{
  it('uses the demo alert candidate for a one-click warning',async()=>{
    const candidate='0x4444444444444444444444444444444444444444';
    const example={...demo,alerts:[{id:'a',wallet_id:'w',kind:'lookalike',severity:'warning',title:'Example',explanation:'Example',action:'Check it',tx_hash:null,block:1,timestamp:null,evidence:{candidate},acknowledged:false,demo:true}]};
    const fetchMock=vi.fn(async (input:string,_options?:RequestInit)=>json(input==='/api/check'?warning:example));
    vi.stubGlobal('fetch',fetchMock);
    render(<App/>);
    fireEvent.click(await screen.findByRole('button',{name:'Try a lookalike example'}));
    expect(await screen.findByText('Possible lookalike')).toBeTruthy();
    expect((screen.getByLabelText('Destination address') as HTMLInputElement).value).toBe(candidate);
    const call=fetchMock.mock.calls.find(([path])=>path==='/api/check');
    expect(JSON.parse((call?.[1] as RequestInit).body as string)).toMatchObject({destination:candidate,demo:true});
  });
  it('describes the service-provided live cadence as a target',async()=>{
    vi.stubGlobal('fetch',vi.fn(async (input:string)=>json(input==='/api/state'?{...live,limits:{max_wallets:3,poll_seconds:300,max_global_wallets:3}}:demo)));
    render(<App/>);
    fireEvent.click(await screen.findByRole('button',{name:'Monitor'}));
    fireEvent.click(screen.getByRole('button',{name:'Live'}));
    expect(await screen.findByText(/Checks target every 5 minutes/)).toBeTruthy();
    expect(screen.getByText(/Delays and provider quotas may apply.*Pilot capacity: 3 wallets total/)).toBeTruthy();
  });
});

describe('updated detection coverage',()=>{
  it('states direct-payment reference limits and does not imply a zero-value event was signed',async()=>{
    vi.stubGlobal('fetch',vi.fn(async (input:string)=>json(input==='/api/state'?live:demo)));
    render(<App/>);
    fireEvent.click(await screen.findByRole('button',{name:'Live'}));
    expect(await screen.findByText(/Monitored references use prior native payments and direct token payments only after a matching successful receipt/)).toBeTruthy();
    expect(screen.getByText(/Routed and smart-wallet token payments are excluded; token verification runs in bounded passes/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'Monitor'}));
    expect(screen.getByText(/Lookalikes can appear as incoming senders or zero-value outgoing token events/)).toBeTruthy();
    expect(screen.getByText(/An event alone does not prove the wallet signed a payment/)).toBeTruthy();
  });
});
