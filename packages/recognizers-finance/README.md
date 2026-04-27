# @nullpii/recognizers-finance

Credit card (Luhn-validated), IBAN (mod-97), SWIFT/BIC recognizers for
[`nullpii`](https://github.com/lBroth/nullpii).

```ts
import { NullPii } from 'nullpii';
import { FINANCE, luhn, iban97 } from '@nullpii/recognizers-finance';

const np = new NullPii();
for (const r of FINANCE) np.addRecognizer(r);
```

All matches tagged `label: 'account_number'`. Validators reject
syntactically-correct-but-checksum-wrong strings.
