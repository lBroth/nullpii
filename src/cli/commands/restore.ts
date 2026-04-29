import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';

export function registerRestore(program: Command): void {
  program
    .command('restore <text>')
    .description('replace placeholders with original PII values from a session vault')
    .requiredOption('-s, --session <id>', 'session id from a previous sanitize call')
    .action(async (text: string, options: { session: string }) => {
      const engine = new NullPii();
      const result = engine.restore(text, options.session);
      await engine.dispose();
      process.stdout.write(`${result.restored}\n`);
    });
}
