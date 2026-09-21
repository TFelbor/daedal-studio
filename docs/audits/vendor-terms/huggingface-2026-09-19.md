# Hugging Face — terms as read on 2026-09-19

Dated archive for the second remote API the code calls. Unlike Pixazo it spends no
money, so it has never been on this routine's radar; it is here because it is the
channel through which **every model weight** reaches the pipeline, and its terms
determine who carries the weight licences.

**Summarised, not reproduced.**

| Source | URL | Retrieved |
|---|---|---|
| Hugging Face Terms of Service | `https://huggingface.co/terms-of-service` | 2026-09-19 |

Effective date the document states: **15 September 2022**. No change since the last
recorded position.

## Where the code touches it

- `server/app.py` calls `https://huggingface.co/api/whoami-v2` to validate `HF_TOKEN`.
- `web/src/pages/PrinterSetup.tsx` links users to `https://huggingface.co/settings/tokens`.
- Every `from_pretrained` on the model path resolves through the Hub.

## What the terms give, and do not

- **Ownership.** Users own what they create. Content downloaded from others is taken
  "at your own risk and subject to these Terms and/or the terms accompanying such
  Content." The Hub conveys nothing of its own.
- **Warranty.** None. Service is "as is" and "as available", with warranties as to
  "accuracy, reliability or benefits" disclaimed. **Hugging Face warrants nothing about
  a third-party model's licence.**
- **Who complies.** Where content "contains notice of a reasonable and customary license
  (such as an open source license) such Content is intended to remain under the terms of
  such license." The downloader complies.
- **Gated repositories.** The Terms of Service say nothing about gating or about who the
  accepting party is when a token unlocks a gated repo. That silence is exactly the hole
  Task L5 identifies for DINOv3: the acceptance is made by whoever holds `HF_TOKEN`, and
  nothing in the platform terms makes it run to a company.
- **Governing law.** State of New York; courts in New York City.

## Standing position

No obligation flows from the Hub itself. Every model obligation this project carries
comes from the individual repository's own licence, which is where
`THIRD-PARTY-NOTICES.md` § 0 records them and where Tasks L4 and L5 sit. Nothing here
changes that; the archive exists so the "Hugging Face warrants nothing" point stops
being an assumption.
