import { describe, expect, it } from 'vitest';
import { changedCharacters, explorerUrl, statePath } from './data';
describe('mode separation',()=>{
  it('loads simulated and live state from separate endpoints',()=>{
    expect(statePath('demo')).toBe('/api/demo');
    expect(statePath('live')).toBe('/api/state');
  });
  it('never turns simulated transaction evidence into a real explorer link',()=>{
    expect(explorerUrl('demo',true,'0xabc')).toBeNull();
    expect(explorerUrl('live',true,'0xabc')).toBeNull();
    expect(explorerUrl('live',false,'0xabc')).toBe('https://basescan.org/tx/0xabc');
  });
});
describe('full address differences',()=>{
  it('highlights only backend-reported positions without truncating the address',()=>{
    const address='0x1234567890abcdef';
    const parts=changedCharacters(address,[4,17]);
    expect(parts.map(p=>p.char).join('')).toBe(address);
    expect(parts.flatMap((p,i)=>p.changed?[i]:[])).toEqual([4,17]);
  });
});
