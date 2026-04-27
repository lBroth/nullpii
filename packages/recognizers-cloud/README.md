# @nullpii/recognizers-cloud

AWS / GCP / Azure / GitHub / Slack / Stripe access-key recognizers for
[`nullpii`](https://github.com/lBroth/nullpii).

```ts
import { NullPii } from 'nullpii';
import { CLOUD_KEYS } from '@nullpii/recognizers-cloud';

const np = new NullPii();
for (const r of CLOUD_KEYS) np.addRecognizer(r);
```

Or pick individuals:

```ts
import { AWS_ACCESS_KEY, GITHUB_PAT } from '@nullpii/recognizers-cloud';
np.addRecognizer(AWS_ACCESS_KEY);
np.addRecognizer(GITHUB_PAT);
```

All matches are tagged `label: 'secret'`. Confidence ≥ 0.95.
