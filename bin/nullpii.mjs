#!/usr/bin/env node
import { run } from '../dist/cli/index.js';

const code = await run(process.argv);
process.exit(code);
