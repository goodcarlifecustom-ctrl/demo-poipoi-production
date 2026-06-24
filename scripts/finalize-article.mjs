#!/usr/bin/env node
import fs from 'node:fs';
import { parseArgs, articleFiles, loadArticle } from './post-wp-draft.mjs';
import { extractWpContent, validateGutenbergArticle } from './gutenberg-article.mjs';

const args = parseArgs();
const article = loadArticle(args.slug);
const next = extractWpContent(article.content).trimEnd() + '\n';
validateGutenbergArticle(next, { title: article.title });
const file = articleFiles(args.slug).html;
const current = fs.readFileSync(file, 'utf8');
if (current !== next) fs.writeFileSync(file, next);
console.log(current === next ? `Finalize idempotent: ${args.slug}` : `Finalized Gutenberg article: ${args.slug}`);
