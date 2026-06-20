#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { parseArgs } from './post-wp-draft.mjs';
const args=parseArgs();
function run(cmd, argv){const r=spawnSync(cmd,argv,{stdio:'inherit',shell:false}); if(r.status!==0) process.exit(r.status||1)}
run('npm',['test']);
run('npm',['run','check','--','--slug',args.slug]);
if(!args.localOnly) run('npm',['run','post','--','--slug',args.slug]);
else console.log('Local-only article completion finished; WordPress posting skipped by explicit option.');
