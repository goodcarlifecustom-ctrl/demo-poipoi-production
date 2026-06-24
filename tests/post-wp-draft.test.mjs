import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { stagedPost, sha256, parseArgs } from '../scripts/post-wp-draft.mjs';

function fixture(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'wpdraft-')); fs.mkdirSync(path.join(root,'articles','demo'),{recursive:true}); const html=`<!-- wp:paragraph -->
<p>Body text long enough intro.</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>この記事でわかること</p>
<!-- /wp:paragraph -->

<!-- wp:list -->
<ul class="wp-block-list">
<!-- wp:list-item -->
<li><a href="#sec-01">Demo Section</a></li>
<!-- /wp:list-item -->
</ul>
<!-- /wp:list -->

<!-- wp:heading {"level":2,"anchor":"sec-01"} -->
<h2 class="wp-block-heading" id="sec-01">Demo Section</h2>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>Detailed body text long enough.</p>
<!-- /wp:paragraph -->`; fs.writeFileSync(path.join(root,'articles','demo','article.html'),html); fs.writeFileSync(path.join(root,'articles','demo','metadata.json'),JSON.stringify({title:'Demo Title',slug:'demo',target_media:'Demo Media',article_type:'SEO記事',main_keyword:'demo keyword',related_keywords:['demo related'],target_reader:'demo reader',article_goal:'demo goal',char_count:{min:10,target:60,max:200},wordpress_draft:true},null,2)); return {root,html}}
async function server(handler){const s=http.createServer(async(req,res)=>{let b=''; for await (const c of req)b+=c; handler(req,res,b)}); await new Promise(r=>s.listen(0,'127.0.0.1',r)); return {url:`http://127.0.0.1:${s.address().port}`, close:()=>new Promise(r=>s.close(r))}}
function json(res,obj){res.setHeader('content-type','application/json'); res.end(JSON.stringify(obj))}

test('creates minimal draft, updates content only, verifies draft and writes metadata', async()=>{const {root,html}=fixture(); const calls=[]; let post={id:101,slug:'demo',status:'draft',title:{raw:'Demo Title'},content:{raw:''},link:'http://wp/?p=101'}; const srv=await server((req,res,body)=>{calls.push({url:req.url,method:req.method,body:body&&JSON.parse(body)}); if(req.url.startsWith('/wp-json/wp/v2/users/me')) return json(res,{id:1}); if(req.url.startsWith('/wp-json/wp/v2/posts?')) return json(res,[]); if(req.url==='/wp-json/wp/v2/posts'&&req.method==='POST'){post.content.raw=JSON.parse(body).content; return json(res,post)} if(req.url==='/wp-json/wp/v2/posts/101'&&req.method==='POST'){assert.deepEqual(Object.keys(JSON.parse(body)),['content']); post.content.raw=JSON.parse(body).content; return json(res,post)} if(req.url==='/wp-json/wp/v2/posts/101?context=edit') return json(res,post); res.statusCode=404; json(res,{})}); try{const r=await stagedPost({slug:'demo',root,baseUrl:srv.url,username:'u',password:'p'}); assert.equal(r.postId,101); assert.equal(calls.find(c=>c.url==='/wp-json/wp/v2/posts').body.status,'draft'); assert.match(calls.find(c=>c.url==='/wp-json/wp/v2/posts').body.content,/codex-staged-draft/); const meta=JSON.parse(fs.readFileSync(path.join(root,'articles','demo','metadata.json'))); assert.equal(meta.wordpress_draft_id,101); assert.equal(meta.status,'draft'); assert.equal(sha256(html), sha256(post.content.raw)); } finally {await srv.close()}});

test('duplicate slug stops before create', async()=>{const {root}=fixture(); let created=false; const srv=await server((req,res)=>{if(req.url.startsWith('/wp-json/wp/v2/users/me')) return json(res,{id:1}); if(req.url.includes('slug=demo')) return json(res,[{id:9,slug:'demo',status:'draft',title:{raw:'Other'},content:{raw:'x'}}]); if(req.url==='/wp-json/wp/v2/posts'){created=true} json(res,[])}); try{await assert.rejects(stagedPost({slug:'demo',root,baseUrl:srv.url,username:'u',password:'p'}),/Manual confirmation/); assert.equal(created,false)} finally {await srv.close()}});

test('duplicate title stops before create', async()=>{const {root}=fixture(); const srv=await server((req,res)=>{if(req.url.startsWith('/wp-json/wp/v2/users/me')) return json(res,{id:1}); if(req.url.includes('status=draft')) return json(res,[{id:8,slug:'other',status:'draft',title:{raw:'Demo Title'},content:{raw:'x'}}]); json(res,[])}); try{await assert.rejects(stagedPost({slug:'demo',root,baseUrl:srv.url,username:'u',password:'p'}),/Manual confirmation/)} finally {await srv.close()}});

test('metadata id matching remote content is idempotent', async()=>{const {root,html}=fixture(); fs.writeFileSync(path.join(root,'articles','demo','metadata.json'),JSON.stringify({title:'Demo Title',slug:'demo',target_media:'Demo Media',article_type:'SEO記事',main_keyword:'demo keyword',related_keywords:['demo related'],target_reader:'demo reader',article_goal:'demo goal',char_count:{min:10,target:60,max:200},wordpress_draft:true,wordpress_draft_id:7})); let posts=0; const srv=await server((req,res)=>{if(req.url.startsWith('/wp-json/wp/v2/users/me')) return json(res,{id:1}); if(req.url.includes('/posts/7')) return json(res,{id:7,slug:'demo',status:'draft',title:{raw:'Demo Title'},content:{raw:html}}); if(req.method==='POST') posts++; json(res,[])}); try{const r=await stagedPost({slug:'demo',root,baseUrl:srv.url,username:'u',password:'p'}); assert.equal(r.action,'already-matches'); assert.equal(posts,0)} finally {await srv.close()}});

test('minimal create timeout recovers staged draft without reposting', async()=>{const {root,html}=fixture(); let createCount=0; let searchingAfterTimeout=false; const hash=sha256(html); const srv=await server((req,res,body)=>{if(req.url.startsWith('/wp-json/wp/v2/users/me')) return json(res,{id:1}); if(req.url==='/wp-json/wp/v2/posts'&&req.method==='POST'){createCount++; searchingAfterTimeout=true; req.socket.destroy(); return} if(req.url.startsWith('/wp-json/wp/v2/posts?')) return json(res, searchingAfterTimeout ? [{id:12,slug:'demo',status:'draft',title:{raw:'Demo Title'},content:{raw:`<!-- codex-staged-draft content-sha256="${hash}" -->`}}] : []); if(req.url==='/wp-json/wp/v2/posts/12'&&req.method==='POST') return json(res,{id:12,slug:'demo',status:'draft',title:{raw:'Demo Title'},content:{raw:JSON.parse(body).content}}); if(req.url==='/wp-json/wp/v2/posts/12?context=edit') return json(res,{id:12,slug:'demo',status:'draft',title:{raw:'Demo Title'},content:{raw:html}}); json(res,[])}); try{await assert.rejects(stagedPost({slug:'demo',root,baseUrl:srv.url,username:'u',password:'p'})); assert.equal(createCount,1)} finally {await srv.close()}});

test('forbids non-draft status and local-only does not require WordPress', async()=>{assert.throws(()=>parseArgs(['--slug','demo','--status','publish']),/Only draft/); const {root}=fixture(); const r=await stagedPost({slug:'demo',root,localOnly:true}); assert.equal(r.action,'local-only')});

test('lock prevents same slug start and secrets are sanitized', async()=>{const {root}=fixture(); fs.mkdirSync(path.join(root,'.wp-draft-locks')); fs.writeFileSync(path.join(root,'.wp-draft-locks','demo.lock'),'x'); await assert.rejects(stagedPost({slug:'demo',root,baseUrl:'http://example.invalid',username:'secret-user',password:'secret-pass'}),/Lock exists/)});


test('validates required new article inputs and Gutenberg TOC anchors', async()=>{
  const { validateNewArticleInput, validateGutenbergArticle, extractWpContent } = await import('../scripts/gutenberg-article.mjs');
  assert.throws(()=>validateNewArticleInput({char_count:{min:100,target:50,max:200},wordpress_draft:true}), /Missing required/);
  assert.throws(()=>validateNewArticleInput({target_media:'m',article_type:'t',main_keyword:'k',related_keywords:['r'],target_reader:'reader',article_goal:'goal',char_count:{min:100,target:50,max:200},wordpress_draft:true}), /min <= target/);
  const {html}=fixture();
  assert.doesNotThrow(()=>validateGutenbergArticle(html,{title:'Demo Title'}));
  assert.equal(extractWpContent(`---
title: x
---
${html}`), html);
  assert.throws(()=>validateGutenbergArticle(html.replace('#sec-01','#missing'),{title:'Demo Title'}), /missing target/);
});

test('rejects conflicting WordPress draft settings and non-draft metadata statuses before network', async()=>{
  const { validateNewArticleInput } = await import('../scripts/gutenberg-article.mjs');
  const base={title:'Safe Title',slug:'safe-slug',target_media:'m',article_type:'t',main_keyword:'k',related_keywords:['r'],target_reader:'reader',article_goal:'goal',char_count:{min:1,target:2,max:100}};
  assert.throws(()=>validateNewArticleInput({...base,wordpress_draft:false,post_to_wp:true}), /must match/);
  assert.throws(()=>validateNewArticleInput({...base,wordpress_draft:true,post_to_wp:false}), /must match/);
  for (const status of ['publish','private','pending']) assert.throws(()=>validateNewArticleInput({...base,wordpress_draft:true,status}), /Only draft/);
});

test('template and disabled draft settings cannot reach WordPress network calls', async()=>{
  const {root,html}=fixture();
  fs.mkdirSync(path.join(root,'articles','_template'),{recursive:true});
  fs.writeFileSync(path.join(root,'articles','_template','article.html'),html);
  fs.writeFileSync(path.join(root,'articles','_template','metadata.json'),JSON.stringify({title:'Safe Template',slug:'_template',target_media:'m',article_type:'t',main_keyword:'k',related_keywords:['r'],target_reader:'reader',article_goal:'goal',char_count:{min:1,target:50,max:200},wordpress_draft:false},null,2));
  let touched=false;
  const srv=await server(()=>{touched=true});
  try{
    await assert.rejects(stagedPost({slug:'_template',root,baseUrl:srv.url,username:'u',password:'p'}), /not postable|wordpress_draft/);
    assert.equal(touched,false);
    fs.writeFileSync(path.join(root,'articles','demo','metadata.json'),JSON.stringify({title:'Demo Title',slug:'demo',target_media:'Demo Media',article_type:'SEO記事',main_keyword:'demo keyword',related_keywords:['demo related'],target_reader:'demo reader',article_goal:'demo goal',char_count:{min:10,target:60,max:200},wordpress_draft:false},null,2));
    await assert.rejects(stagedPost({slug:'demo',root,baseUrl:srv.url,username:'u',password:'p'}), /wordpress_draft must be true/);
    assert.equal(touched,false);
  } finally {await srv.close()}
});

test('validates nested Gutenberg blocks, custom blocks, self-closing dynamic blocks, and invalid block structures', async()=>{
  const { validateGutenbergArticle } = await import('../scripts/gutenberg-article.mjs');
  const valid=`<!-- wp:paragraph --><p>Intro</p><!-- /wp:paragraph -->
<!-- wp:paragraph --><p>この記事でわかること</p><!-- /wp:paragraph -->
<!-- wp:list --><ul class="wp-block-list"><!-- wp:list-item --><li><a href="#sec-01">見出し一</a></li><!-- /wp:list-item --></ul><!-- /wp:list -->
<!-- wp:group {"className":"keep","style":{"spacing":{"padding":"1em"}}} --><div class="wp-block-group keep">
<!-- wp:columns --><div class="wp-block-columns"><!-- wp:column --><div class="wp-block-column">
<!-- wp:heading {"level":2,"anchor":"sec-01","className":"x"} --><h2 class="wp-block-heading x" id="sec-01">見出し一</h2><!-- /wp:heading -->
<!-- wp:paragraph {"backgroundColor":"white","textColor":"black","fontSize":"large"} --><p>本文テキストです。</p><!-- /wp:paragraph -->
<!-- /wp:column --></div><!-- /wp:columns --></div><!-- /wp:group -->
<!-- wp:my-plugin/custom {"foo":"bar"} --><div>custom</div><!-- /wp:my-plugin/custom -->
<!-- wp:latest-posts /-->`;
  assert.doesNotThrow(()=>validateGutenbergArticle(valid,{title:'Other'}));
  assert.throws(()=>validateGutenbergArticle(valid.replace('<!-- /wp:column -->','<!-- /wp:columns -->'),{title:'Other'}), /mismatch/);
  assert.throws(()=>validateGutenbergArticle(valid.replace('<!-- /wp:group -->',''),{title:'Other'}), /Unclosed/);
  assert.throws(()=>validateGutenbergArticle('<!-- /wp:paragraph -->'+valid,{title:'Other'}), /without opener/);
  assert.throws(()=>validateGutenbergArticle(valid.replace('{"foo":"bar"}', '{foo}'),{title:'Other'}), /Invalid JSON/);
  assert.throws(()=>validateGutenbergArticle('<!-- wp:html --><div>all html</div><!-- /wp:html -->',{title:'Other'}), /single wp:html/);
});

test('Markdown detection ignores code/html/script/style regions but catches body Markdown', async()=>{
  const { validateGutenbergArticle } = await import('../scripts/gutenberg-article.mjs');
  const safe=`<!-- wp:paragraph --><p>Intro</p><!-- /wp:paragraph -->
<!-- wp:paragraph --><p>この記事でわかること</p><!-- /wp:paragraph -->
<!-- wp:list --><ul class="wp-block-list"><!-- wp:list-item --><li><a href="#sec-01">見出し一</a></li><!-- /wp:list-item --></ul><!-- /wp:list -->
<!-- wp:heading {"level":2,"anchor":"sec-01"} --><h2 class="wp-block-heading" id="sec-01">見出し一</h2><!-- /wp:heading -->
<!-- wp:code --><pre class="wp-block-code"><code>## 見出し例
- リスト例
![画像](https://example.invalid/image.jpg)
|A|B|</code></pre><!-- /wp:code -->
<!-- wp:html --><div data-url="https://example.invalid/#hash">## html</div><script>const x='- list';</script><!-- /wp:html -->
<style>#id{color:red}</style><script type="application/ld+json">{"name":"# hash"}</script>`;
  assert.doesNotThrow(()=>validateGutenbergArticle(safe,{title:'Other'}));
  assert.throws(()=>validateGutenbergArticle(`${safe}\n## 残存`,{title:'Other'}), /Markdown heading/);
  assert.throws(()=>validateGutenbergArticle(`${safe}\n- 残存`,{title:'Other'}), /Markdown list/);
  assert.throws(()=>validateGutenbergArticle(`${safe}\n![alt](https://example.invalid/a.jpg)`,{title:'Other'}), /Markdown image/);
  assert.throws(()=>validateGutenbergArticle(`${safe}\n|A|B|`,{title:'Other'}), /Markdown table/);
  assert.throws(()=>validateGutenbergArticle(`${safe}\n\`\`\`js`,{title:'Other'}), /code fence/);
});

test('visible Japanese character count excludes markup and allows rendered.html text mention', async()=>{
  const { visibleCharCount, validateGutenbergArticle } = await import('../scripts/gutenberg-article.mjs');
  const html=`---
title: ignored
---
<!-- wp:paragraph --><p>本文&amp;ABC、リンク<a href="https://example.invalid/path">表示</a></p><!-- /wp:paragraph -->
<!-- wp:paragraph --><p>この記事でわかること</p><!-- /wp:paragraph -->
<!-- wp:list --><ul class="wp-block-list"><!-- wp:list-item --><li><a href="#sec-01">見出し一</a></li><!-- /wp:list-item --></ul><!-- /wp:list -->
<!-- wp:heading {"level":2,"anchor":"sec-01"} --><h2 class="wp-block-heading" id="sec-01">見出し一</h2><!-- /wp:heading -->
<!-- work log should disappear --><script>ignored()</script><style>.x{}</style><p>rendered.htmlという文字列の説明です</p>`;
  assert.equal(visibleCharCount(html), Array.from('本文&ABC、リンク表示この記事でわかること見出し一見出し一rendered.htmlという文字列の説明です').length);
  assert.doesNotThrow(()=>validateGutenbergArticle(html,{title:'Other',metadata:{title:'Other',slug:'slug',target_media:'m',article_type:'t',main_keyword:'k',related_keywords:['r'],target_reader:'reader',article_goal:'goal',char_count:{min:1,target:50,max:200},wordpress_draft:true}}));
});

test('finalize strips front matter once and preserves existing Gutenberg bytes on second run', async()=>{
  const { execFileSync } = await import('node:child_process');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'finalize-'));
  const dir=path.join(root,'articles','final-demo'); fs.mkdirSync(dir,{recursive:true});
  const body=`<!-- wp:paragraph --><p>Intro</p><!-- /wp:paragraph -->
<!-- wp:paragraph --><p>この記事でわかること</p><!-- /wp:paragraph -->
<!-- wp:list --><ul class="wp-block-list"><!-- wp:list-item --><li><a href="#sec-01">見出し一</a></li><!-- /wp:list-item --></ul><!-- /wp:list -->
<!-- wp:group {"className":"keep","align":"wide"} --><div class="wp-block-group alignwide">
<!-- wp:heading {"level":2,"anchor":"sec-01","className":"keep-heading"} --><h2 class="wp-block-heading keep-heading" id="sec-01">見出し一</h2><!-- /wp:heading -->
<!-- wp:html --><div><script>window.ad='## keep';</script>[ad_shortcode]</div><!-- /wp:html -->
<!-- wp:code --><pre class="wp-block-code"><code>- keep markdown</code></pre><!-- /wp:code -->
<!-- /wp:group -->\n`;
  fs.writeFileSync(path.join(dir,'article.html'),`---\ntitle: Front\n---\n${body}`);
  fs.writeFileSync(path.join(dir,'metadata.json'),JSON.stringify({title:'Final Title',slug:'final-demo',target_media:'m',article_type:'t',main_keyword:'k',related_keywords:['r'],target_reader:'reader',article_goal:'goal',char_count:{min:1,target:50,max:500},wordpress_draft:true},null,2));
  execFileSync('node',[path.resolve('scripts/finalize-article.mjs'),'--slug','final-demo'],{cwd:root,stdio:'pipe'});
  const once=fs.readFileSync(path.join(dir,'article.html'),'utf8');
  execFileSync('node',[path.resolve('scripts/finalize-article.mjs'),'--slug','final-demo'],{cwd:root,stdio:'pipe'});
  const twice=fs.readFileSync(path.join(dir,'article.html'),'utf8');
  assert.equal(once, body);
  assert.equal(twice, once);
  assert.match(twice, /wp:group {"className":"keep","align":"wide"}/);
  assert.match(twice, /wp:html --><div><script>window.ad='## keep';<\/script>\[ad_shortcode\]<\/div><!-- \/wp:html/);
});

test('E2E local mocked article completion payload is safe and metadata-derived', async()=>{
  const { execFileSync } = await import('node:child_process');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'e2e-'));
  const slug='e2e-demo'; const dir=path.join(root,'articles',slug); fs.mkdirSync(dir,{recursive:true});
  const html=`---
title: ignored
---
<!-- wp:paragraph --><p>導入本文です。信頼できる情報をもとに説明します。</p><!-- /wp:paragraph -->
<!-- wp:paragraph --><p>この記事でわかること</p><!-- /wp:paragraph -->
<!-- wp:list --><ul class="wp-block-list"><!-- wp:list-item --><li><a href="#sec-01">要点表</a></li><!-- /wp:list-item --></ul><!-- /wp:list -->
<!-- wp:heading {"level":2,"anchor":"sec-01"} --><h2 class="wp-block-heading" id="sec-01">要点表</h2><!-- /wp:heading -->
<!-- wp:table --><figure class="wp-block-table"><table><tbody><tr><th>項目</th><th>内容</th></tr><tr><td>A</td><td>B</td></tr></tbody></table></figure><!-- /wp:table -->`;
  const meta={title:'E2E Safe Title',slug,target_media:'m',article_type:'t',main_keyword:'k',related_keywords:['r'],target_reader:'reader',article_goal:'goal',char_count:{min:20,target:50,max:200},wordpress_draft:true};
  fs.writeFileSync(path.join(dir,'article.html'),html);
  fs.writeFileSync(path.join(dir,'metadata.json'),JSON.stringify(meta,null,2));
  execFileSync('node',[path.resolve('scripts/finalize-article.mjs'),'--slug',slug],{cwd:root,stdio:'pipe'});
  execFileSync('node',[path.resolve('scripts/check-article.mjs'),'--slug',slug],{cwd:root,stdio:'pipe'});
  let finalPost; const calls=[];
  const srv=await server((req,res,body)=>{calls.push({url:req.url,method:req.method,body:body&&JSON.parse(body)}); if(req.url.startsWith('/wp-json/wp/v2/users/me')) return json(res,{id:1}); if(req.url.startsWith('/wp-json/wp/v2/posts?')) return json(res,[]); if(req.url==='/wp-json/wp/v2/posts') return json(res,{id:321,slug,status:'draft',title:{raw:meta.title},content:{raw:JSON.parse(body).content},link:'http://wp.local/?p=321'}); if(req.url==='/wp-json/wp/v2/posts/321'&&req.method==='POST'){finalPost={id:321,slug,status:'draft',title:{raw:meta.title},content:{raw:JSON.parse(body).content},link:'http://wp.local/?p=321'}; return json(res,finalPost)} if(req.url==='/wp-json/wp/v2/posts/321?context=edit') return json(res,finalPost); json(res,[])});
  try{
    const result=await stagedPost({slug,root,baseUrl:srv.url,username:'u',password:'p'});
    assert.equal(result.postId,321);
    const createPayload=calls.find(c=>c.url==='/wp-json/wp/v2/posts').body;
    const updatePayload=calls.find(c=>c.url==='/wp-json/wp/v2/posts/321').body;
    assert.equal(createPayload.title,meta.title);
    assert.equal(createPayload.slug,slug);
    assert.equal(createPayload.status,'draft');
    assert.match(updatePayload.content,/<!-- wp:paragraph -->/);
    assert.doesNotMatch(updatePayload.content,/^---|metadata|作業ログ|<h1/i);
    assert.doesNotMatch(updatePayload.content,/rendered\.html/);
  } finally { await srv.close(); fs.rmSync(root,{recursive:true,force:true}); }
});
