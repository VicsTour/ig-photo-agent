# ig-photo-agent

Claude proposes Instagram posts from my Lightroom exports; I approve from the Claude app; GitHub Actions publishes.

```
Lightroom ──export──▶ inbox/ ──Claude (scheduled task)──▶ proposal on iPhone
                                                        │ "ok"
                                                        ▼
                         queue/<slug>/photo.jpg + post.json
                                                        │ GitHub Action, every 15 min
                                                        ▼
                                    Instagram ──▶ posted/ + log/posts.csv
```

- Agent instructions: `CLAUDE.md` · My voice and posting times: `config/profile.md`
- Secrets (GitHub → Settings → Secrets → Actions): `IG_ACCESS_TOKEN`, `GH_PAT`
- Nothing secret is stored in this repo. Public copies of photos have all metadata (incl. GPS) stripped.
