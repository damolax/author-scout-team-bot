// Pure graph layout helpers; draft-only, never sends a message.
export const NODE_W=226,NODE_H=106,X_GAP=106,Y_GAP=42
export function hasPath(doc,from,to){
  const seen=new Set(),stack=[from]
  while(stack.length){const p=stack.pop();if(p===to)return true;if(seen.has(p))continue;seen.add(p)
    for(const e of (doc.edges||[])){if(e.from===p&&e.to)stack.push(e.to)}}
  return false
}
export function canLink(doc,from,to,outcome){
  const by=new Map((doc.nodes||[]).map(n=>[n.code,n]))
  if(!by.has(from)||!by.has(to))return 'Choose two existing messages'
  if(from===to||hasPath(doc,to,from))return 'That link would make a circular conversation'
  if(['terminal','success'].includes(by.get(from).stage))return 'Completed messages cannot have next steps'
  if(by.get(to).stage==='terminal')return 'Stop nodes cannot be sendable message targets'
  if((doc.edges||[]).some(e=>e.from===from&&e.outcome===outcome))return 'This message already has that response path'
  return null
}
export function autoLayout(doc){
  const nodes=doc?.nodes||[],edges=doc?.edges||[]
  if(!nodes.length)return {positions:{},width:670,height:440}
  const all=new Set(nodes.map(n=>n.code))
  const root=all.has('Message01')?'Message01':nodes[0].code
  const out=new Map(nodes.map(n=>[n.code,[]]))
  for(const e of edges){if(e.to&&all.has(e.from)&&all.has(e.to))out.get(e.from).push(e)}
  const outcomes=['yes','positive','question','objection','no','not_now','no_reply','uncertain','negative','opt_out','bounce']
  for(const children of out.values())children.sort((a,b)=>outcomes.indexOf(a.outcome)-outcomes.indexOf(b.outcome))
  const depths=new Map([[root,0]]),queue=[root]
  while(queue.length){const from=queue.shift();for(const edge of out.get(from)||[]){
    if(!depths.has(edge.to)){depths.set(edge.to,depths.get(from)+1);queue.push(edge.to)}
  }}
  const widest=Math.max(...depths.values(),0)
  for(const n of nodes)if(!depths.has(n.code))depths.set(n.code,widest+1)
  const columns=new Map()
  for(const n of nodes){const d=depths.get(n.code);if(!columns.has(d))columns.set(d,[]);columns.get(d).push(n.code)}
  // Barycentric pass: nodes with the same parent remain neighbors.
  const index=new Map([[root,0]])
  for(const [d,items] of [...columns].sort((a,b)=>a[0]-b[0])){
    if(d===0){items.forEach((v,i)=>index.set(v,i));continue}
    items.sort((a,b)=>{
      const parents=n=>edges.filter(e=>e.to===n&&index.has(e.from))
       .map(e=>index.get(e.from))
      const avg=arr=>arr.length?arr.reduce((x,y)=>x+y,0)/arr.length:1e6
      return avg(parents(a))-avg(parents(b))||a.localeCompare(b)
    });items.forEach((v,i)=>index.set(v,i))
  }
  const positions={},padding=36
  for(const [d,items] of columns){items.forEach((code,i)=>positions[code]={x:padding+d*(NODE_W+X_GAP),y:padding+i*(NODE_H+Y_GAP)})}
  return {positions,width:Math.max(670,(Math.max(...columns.keys())+1)*(NODE_W+X_GAP)+90),
    height:Math.max(460,Math.max(...[...columns.values()].map(x=>x.length))* (NODE_H+Y_GAP)+90)}
}
export function orthogonalPath(from,to){
  const ax=from.x+NODE_W,ay=from.y+NODE_H/2,bx=to.x,by=to.y+NODE_H/2
  if(bx>ax+30){const mid=ax+Math.max(30,(bx-ax)/2);return `M ${ax} ${ay} H ${mid} V ${by} H ${bx-6}`}
  // Non-forward shared destinations get a small routed jump below their source,
  // avoiding the long direct diagonal from the previous version.
  const mid=ay+NODE_H/2+24,enter=bx-30
  return `M ${ax} ${ay} H ${ax+20} V ${mid} H ${enter} V ${by} H ${bx-6}`
}
