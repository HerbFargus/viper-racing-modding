import sys; sys.path.insert(0,'../..'); sys.path.insert(0,'.')
import kit
from kit import cockpit
from kit.shapes import Builder
import cvd_models as M
for name,make,ck in (('alleycat',M.alley_cat,M.alley_cat_cockpit),('doghouse',M.doghouse,M.doghouse_cockpit)):
    m=make(); c=ck(m['body'])
    extra=Builder()
    for g in c['gauges'].values():
        extra.cyl([g[0],g[1],g[2]+.01], c['gauge_r']*1.1, .01, '#d8d8d0', n=16, rot=(-1.5708,0,0))
    extra.cyl([c['wheel'][0],c['wheel'][1],c['wheel'][2]], c['wheel_R'], .03, '#222222', n=20, rot=(-1.5708,0,0))
    scene=Builder().extend(Builder().extend(c['shell']).extend(cockpit.toward(c['inside'], c['eye']) if c.get('inside') else Builder())).extend(cockpit.toward(extra, c['eye']))
    cockpit.snapshot('out/'+name+'-seat.png', c['eye'], scene)
