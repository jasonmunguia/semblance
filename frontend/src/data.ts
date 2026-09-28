export type Mode = 'demo' | 'live';
export function statePath(mode:Mode){return mode==='demo'?'/api/demo':'/api/state'}
export function explorerUrl(mode:Mode, demo:boolean, txHash:string|null){return mode==='live'&&!demo&&txHash?`https://basescan.org/tx/${encodeURIComponent(txHash)}`:null}
export function tokenExplorerUrl(mode:Mode, demo:boolean, address:string|null|undefined){return mode==='live'&&!demo&&address?`https://basescan.org/address/${encodeURIComponent(address)}`:null}
export function changedCharacters(candidate:string, indices:number[]){const changed=new Set(indices);return [...candidate].map((char,index)=>({char,changed:changed.has(index)}))}
