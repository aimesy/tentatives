# archive/el-dorado/

Content-addressable storage for El Dorado County tentative-ruling PDFs.

```
archive/el-dorado/
├── <sha[:2]>/<sha>.pdf      raw PDF, named by sha256 of its bytes
├── captures.ndjson          append-only log of fetch events
└── README.md                you are here
```

A capture row (one line of `captures.ndjson`):

```json
{
  "source_sha256": "65bf1512...",
  "source_url": "https://www.eldorado.courts.ca.gov/system/files/tentative-rulings/tr-d-09-2026-05-18.pdf",
  "discovered_filename": "tr-d-09-2026-05-18.pdf",
  "fetched_at": "2026-05-19T00:00:00Z",
  "wayback_ts": null,
  "content_length": 389234
}
```

Re-captures of the same PDF append another row; the file itself is written once.
