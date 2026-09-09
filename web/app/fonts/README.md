# DATA:EZ UI fonts

Spoqa Han Sans Neo was selected by the user on 2026-09-09. `app/layout.tsx` loads the local 400, 500 and 700 WOFF2 files through `next/font/local`.

These unmodified files come from the official Spoqa Han Sans Neo v3.3.0 subset distribution. Noto Sans KR is the local fallback for characters outside that subset; its WOFF2 file is losslessly packaged from the pinned upstream TTF with no glyph edits or subsetting.

Original source URLs, versions, hashes, glyph coverage and font features are recorded in `public/font-licenses/manifest.json`. Original copyright and license texts are in the same directory and served at `/font-licenses/`.

Use regular 400 for body text, medium 500 for emphasis, and bold 700 for headings and primary amounts. Tailwind `font-semibold` maps to the supplied 700 weight. Financial values use the sans family and the `numeric` class; SQL and JSON retain the code font.
