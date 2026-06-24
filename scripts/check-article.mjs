#!/usr/bin/env node
import { parseArgs, loadArticle } from './post-wp-draft.mjs';
import { validateGutenbergArticle, validateNewArticleInput } from './gutenberg-article.mjs';
try {
  const {slug}=parseArgs();
  const a=loadArticle(slug);
  if(a.content.length < 20) throw new Error('Article body is below minimum length');
  if(/href=["']https?:\/\/[^"']+["'][^>]*>https?:\/\//i.test(a.content)) throw new Error('Visible raw external URL detected');
  if(a.files.mode==='dir') validateNewArticleInput(a.metadata);
  validateGutenbergArticle(a.content,{title:a.title,metadata:a.files.mode==='dir'?a.metadata:null});
  console.log(`Article validation PASS: ${slug}`);
} catch(e) {
  console.error(e.message);
  process.exit(1);
}
