import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, ref, nextTick } from 'vue'

test('inline task input focuses, edits independently and returns focus without an expansion panel', async () => {
  const dir = await mkdtemp(new URL('../.composer-test-', import.meta.url).pathname)
  let focused
  const node = (type, text='') => ({type,text,children:[],props:{},parent:null,focus(){focused=this},showModal(){this.open=true},close(){this.open=false}})
  const renderer = createRenderer({
    createElement: type => node(type), createText: text => node('text',text), createComment: text => node('comment',text),
    setText: (n,text) => n.text=text, setElementText: (n,text) => {n.text=text;n.children=[]},
    parentNode:n=>n.parent, nextSibling:n=>n.parent?.children[n.parent.children.indexOf(n)+1],
    patchProp:(n,k,prev,value)=>n.props[k]=value,
    insert(n,p,anchor){if(n.parent) n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=p;const i=p.children.indexOf(anchor);p.children.splice(i<0?p.children.length:i,0,n)},
    remove(n){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1)},
  })
  let received
  globalThis.__draftApi = { background: async value => { received=value;return {data:{status:'ready',facts:[{source:'当前主输入',quote:'北京'}],reason:'补充地区'}} } }
  try {
    const {descriptor} = parse(await readFile(new URL('../src/components/CollaborationComposer.vue',import.meta.url),'utf8'))
    const code = compileScript(descriptor,{id:'composer',inlineTemplate:true}).content
      .replace("import { collaborationApi } from '../api/index.js'",'const collaborationApi = globalThis.__draftApi')
      .replace("'../utils/collaborationDrafts.js'",JSON.stringify(new URL('../src/utils/collaborationDrafts.js',import.meta.url).href))
    await writeFile(`${dir}/component.mjs`,code)
    const {default:Composer}=await import(`${dir}/component.mjs`)
    const drafts=ref(['a','b'].map((id,i)=>({agent_id:id,name:id,agent_type:i?'llm':'proxy',task:'初始任务',constraints:[],expected_output:'建议',supplemental_prompt:null,depends_on:[]})))
    const root=node('root')
    let composer
    let finished = 0
    const app=renderer.createApp({render:()=>h(Composer,{ref:value=>composer=value,drafts:drafts.value,input:'整体需求',conversationId:'conv',onFinish:()=>finished++,onUpdate:(id,changes)=>{drafts.value=drafts.value.map(d=>d.agent_id===id?{...d,...changes}:d)}})})
    app.mount(root)
    const all=(n=root)=>[n,...n.children.flatMap(c=>all(c))]
    assert.ok(!all().some(n=>n.type==='textarea'))
    await composer.focusTask('a')
    await nextTick()
    assert.equal(focused?.props.id, 'task-a')
    all().find(n=>n.props.id==='task-a').props.onInput({target:{value:'只查询浙江'}})
    await nextTick()
    assert.equal(drafts.value[0].task,'只查询浙江')
    assert.equal(drafts.value[1].task,'初始任务')
    assert.ok(!all().some(n=>['fieldset','details','textarea'].includes(n.type)))
    const input = all().find(n=>n.props.id==='task-a')
    let prevented = 0
    input.props.onKeydown({key:'Enter', isComposing:true, preventDefault(){prevented++}, stopPropagation(){}})
    assert.equal(finished, 0)
    input.props.onKeydown({key:'Enter', preventDefault(){prevented++}, stopPropagation(){}})
    input.props.onKeydown({key:'Escape', preventDefault(){prevented++}, stopPropagation(){}})
    assert.equal(finished, 2)
    assert.equal(prevented, 2)
    assert.ok(!all().some(n=>['dialog','select','textarea'].includes(n.type)))
    const policies = all().filter(n=>n.props.class==='context-policy').map(n=>n.text)
    assert.deepEqual(policies, ['Proxy · 仅任务', 'LLM · 带上下文'])
    app.unmount()
  } finally {delete globalThis.__draftApi;await rm(dir,{recursive:true,force:true})}
})
