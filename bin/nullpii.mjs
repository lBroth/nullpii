#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
import { run } from '../dist/cli/index.js';

const code = await run(process.argv);
process.exit(code);
