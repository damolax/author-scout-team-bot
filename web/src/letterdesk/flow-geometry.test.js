import test from 'node:test'
import assert from 'node:assert/strict'
import {autoLayout,orthogonalPath,canLink,hasPath} from './flow-geometry.js'

const flow={
  nodes:[{code:'Message01',stage:'initial'},
    {code:'Message0101Yes',stage:'interested'},
    {code:'Message0101No',stage:'alternative'},
    {code:'Message0201Yes',stage:'generic'},
    {code:'Message0101OptOut',stage:'terminal'}],
  edges:[{from:'Message01',to:'Message0101Yes',outcome:'yes'},
         {from:'Message01',to:'Message0101No',outcome:'no'},
         {from:'Message0101Yes',to:'Message0201Yes',outcome:'yes'}]
}
test('each message occupies a valid canvas position',()=>{
  const a=autoLayout(flow)
  assert.equal(Object.keys(a.positions).length,flow.nodes.length)
  assert.ok(a.positions.Message0101Yes.x>a.positions.Message01.x)
  assert.ok(a.width>700)
  assert.ok(a.height>=460)
})
test('connector uses horizontal and vertical segments, no long bezier diagonals',()=>{
 const a=autoLayout(flow)
 const p=orthogonalPath(a.positions.Message01,a.positions.Message0101Yes)
 assert.match(p,/^M /);assert.match(p,/ H /);assert.match(p,/ V /)
 assert.doesNotMatch(p,/[CLQ]/)
})
test('refuses loops, duplicate responses and outgoing terminal steps',()=>{
 assert.ok(hasPath(flow,'Message01','Message0201Yes'))
 assert.match(canLink(flow,'Message0201Yes','Message01','yes'),/circular/)
 assert.match(canLink(flow,'Message01','Message0201Yes','no'),/already/)
 assert.match(canLink(flow,'Message0101OptOut','Message0101Yes','yes'),/Completed/)
 assert.match(canLink(flow,'Message0101Yes','Message0101OptOut','question'),/Stop nodes/)
 assert.equal(canLink(flow,'Message0101No','Message0201Yes','question'),null)
})
