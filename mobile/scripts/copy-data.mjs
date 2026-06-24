import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..', '..');
const source = resolve(root, 'data', 'mcq_bank.json');
const target = resolve(root, 'mobile', 'public', 'data', 'mcq_bank.json');

mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
console.log(`Copied ${source} -> ${target}`);
