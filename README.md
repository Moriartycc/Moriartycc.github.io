# Chen Cheng — academic homepage

Personal academic website published with GitHub Pages and Jekyll.

## Active content

- Homepage: `_pages/about.md`
- Publications: `_data/publications.yml` and `_includes/publications-list.html`
- Teaching: `_pages/teaching.html`
- CV: `files/cv/cv.tex` and `files/cv/cv.pdf`
- Cycling: `_pages/cycling.md`
- Research-theme map: `_includes/research-theme-map.html`

## Research-theme data

The controlled concepts and paper sources are defined in
`scripts/research_theme_concepts.json`. To refresh the corpus-derived scores:

```powershell
python scripts/build_research_theme_scores.py
node scripts/validate_research_theme_map.js
```

The rebuild writes `_data/research_theme_scores.json`. Review the homepage
interactions before publishing changes to concepts, sources, or relevance
scores.

## Publication and CV updates

Keep the first-preprint chronology in `_data/publications.yml`. Mirror verified
bibliographic and status changes in `files/cv/cv.tex`, compile `files/cv/cv.pdf`,
and check that the embedded CV page still renders correctly.

The daily Codex maintenance review is preview-only: it proposes source-backed
updates for approval and does not modify or publish the site automatically.

## Local preview

```powershell
bundle install
bundle exec jekyll serve
```

Generated directories such as `_site`, `.sass-cache`, and `vendor` are ignored
and should not be committed.
