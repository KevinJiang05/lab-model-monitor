# Third-party notices

The root [MIT license](LICENSE) applies to this project's original code and documentation. It does not replace licenses or notices supplied by other rights holders.

## Vendored source and project scaffold

- `build/sites-vite-plugin.ts` identifies its source as `@openai/sites-vite-plugin` 0.2.0 (`openai/sites#9`), copyright 2026 OpenAI. Its complete MIT license is preserved in [build/sites-vite-plugin.LICENSE](build/sites-vite-plugin.LICENSE).
- The website began from a Sites scaffold. The existing build and preview adapters retain that structure; the laboratory monitor, evidence contracts, console and result displays are developed in this repository. The project does not claim authorship of third-party scaffold code.

## Dependencies

JavaScript dependency versions are recorded in `package-lock.json`. Their upstream licenses remain applicable; the root license does not relicense dependencies. The direct runtime dependencies currently declare:

| Package | License |
| --- | --- |
| Next.js, React, React DOM, Recharts, Zod | MIT |
| Drizzle ORM | Apache-2.0 |
| Lucide React | ISC |

The build toolchain includes Vinext, Vite and Cloudflare tooling under their own licenses. Consult each installed package's license and notices when redistributing it. The Python monitor has no third-party runtime dependencies.

## Model-generated examples

`public/animations/astra.png` and `public/animations/sol.png` are thumbnails of historical animation outputs used by this project's display. The website matches them to specific HTML hashes as a fallback; they are not a current result snapshot or a visual quality endorsement.

Model responses, generated HTML and their thumbnails are experimental outputs. The root source-code license does not establish exclusive ownership or grant rights to third-party content that may appear in an output. Anyone redistributing an output should assess it separately from the software.

The README screenshot shows the already-public demonstration dashboard on 2026-10-23. Model and product names identify configured endpoints or tools and do not imply affiliation or endorsement.
