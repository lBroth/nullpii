# @nullpii/recognizers-id-it

Italian government-id recognizers (codice fiscale, partita IVA) for
[`nullpii`](https://github.com/lBroth/nullpii). Both validators check the
official checksum.

```ts
import { NullPii } from 'nullpii';
import { ITALIAN_IDS } from '@nullpii/recognizers-id-it';

const np = new NullPii();
for (const r of ITALIAN_IDS) np.addRecognizer(r);
```
