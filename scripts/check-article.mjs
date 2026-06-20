#!/usr/bin/env node
import { parseArgs, loadArticle } from './post-wp-draft.mjs';
try { const {slug}=parseArgs(); const a=loadArticle(slug); if(a.content.length < 20) throw new Error('Article body is below minimum length'); if(/href=["']https?:\/\/[^"']+["'][^>]*>https?:\/\//i.test(a.content)) throw new Error('Visible raw external URL detected'); console.log(`Article validation PASS: ${slug}`); } catch(e) { console.error(e.message); process.exit(1); }
