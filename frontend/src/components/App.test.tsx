import {describe,it,expect,vi} from 'vitest';
import {redirectLegacyHash} from '../navigation';
describe('App legacy hash route adapter',()=>{
 for(const route of ['projects','trash','project/123','episode/123/edit','episode/123/review/job']) {
  it(`translates #${route}`,()=>{const replace=vi.fn();redirectLegacyHash('#'+route,replace);expect(replace).toHaveBeenCalledWith('/'+route);});
 }
 it('ignores an unknown hash',()=>{const replace=vi.fn();redirectLegacyHash('#unknown',replace);expect(replace).not.toHaveBeenCalled();});
});
