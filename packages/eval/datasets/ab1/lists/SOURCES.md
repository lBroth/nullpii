# Sources of the value lists

All lists in this directory are frozen with the benchmark; `gen/build.py` reads only these files.
`gen/fetch_lists.py` is the script that produced the downloaded ones (raw responses were cached under
`cache/lists/`, which is not part of the frozen set). Retrieval date for every downloaded source:
**2026-10-23**. No list comes from Faker or from any PII-masking tool.

## names/<lang>/given_male.txt, given_female.txt, surnames.txt (en, it, de, fr, es)

- Source: Wikidata, via the SPARQL endpoint https://query.wikidata.org/sparql
- Licence: CC0 1.0 (Wikidata structured data)
- Revision: live query on 2026-10-23 (Wikidata has no release tags; the frozen files are the revision)
- Query (one per class × language; `CLASS` = `Q12308941` male given name, `Q11879590` female given name,
  `Q101352` family name; `LANG` = `Q1860` English, `Q652` Italian, `Q188` German, `Q150` French, `Q1321` Spanish):

  ```sparql
  SELECT ?item ?label ?sl WHERE {
    ?item wdt:P31 wd:CLASS; wdt:P407 wd:LANG; wikibase:sitelinks ?sl. FILTER(?sl >= 0)
    ?item rdfs:label ?label. FILTER(LANG(?label) IN ("<lang>", "mul"))
  }
  ```
- Processing: rows ranked by number of sitelinks (descending, ties by item id), labels kept if they look
  like a single capitalised name (letters, apostrophe, at most one space or hyphen), 3–18 characters,
  de-duplicated; first 700 given names per gender and 1,500 family names kept (fewer where Wikidata has fewer:
  de female 478, fr female 641, es female 626).

## streets/<country>.txt (us, gb, it, de, fr, es)

- Source: Wikidata, items that are instances of *street* (`Q79007`) with country (`P17`) = United States (`Q30`),
  United Kingdom (`Q145`), Italy (`Q38`), Germany (`Q183`), France (`Q142`), Spain (`Q29`)
- Licence: CC0 1.0
- Revision: live query on 2026-10-23
- Query: `SELECT ?s ?label WHERE { ?s wdt:P31 wd:Q79007; wdt:P17 wd:COUNTRY; rdfs:label ?label. FILTER(LANG(?label) = "<lang>") }`
- Processing: parenthesised disambiguations and text after a comma removed; labels with digits or longer
  than 40 characters dropped; kept only if they carry a street-type word of the country (e.g. *Via/Viale/Corso*,
  *-straße/-weg/Platz*, *Rue/Avenue/Boulevard*, *Calle/Avenida/Paseo*, *Street/Road/Lane*); first letter
  capitalised; de-duplicated, sorted; where more than 3,000 remained, a seeded sample of 3,000
  (seed = `derive_seed("street-sample", country)`). Street names are real; the addresses built from them
  (random house number + a random postcode/place of the same country) are fictional combinations.

## postal/<country>.tsv (us, gb, it, de, fr, es)

- Source: GeoNames postal code dumps, https://download.geonames.org/export/zip/ (`US.zip`, `GB_full.csv.zip`,
  `IT.zip`, `DE.zip`, `FR.zip`, `ES.zip`)
- Licence: Creative Commons Attribution 4.0 (CC BY 4.0), © GeoNames (https://www.geonames.org/)
- Revision: files downloaded 2026-10-23; SHA-256 of the downloaded archives:

  | file | sha256 |
  |---|---|
  | US.zip | fe924ef45fda91f98f99578a2e9211133dbf5503d4bbfd7c8d5dfdd7cffdcdc3 |
  | GB_full.csv.zip | 627e225609807dd77566e4992cafdef22036bfa1e40b01aea62e9a37bd62d20a |
  | IT.zip | a027779bb6e56d1083a343c32dfb85194f296b6300cecbcc6ef6da0595c908c4 |
  | DE.zip | a280728aee44f89862fd77a76457e0d8fe4600531eb4d0dfe0bb1bc4c01d7428 |
  | FR.zip | 349902026d58322455efd95de500826a054c01966d8072601e99107c8bb58f73 |
  | ES.zip | bbbb3d02f1ba872fe00607a758f59d327a2113e6c722ab5d444f7f8fa8a28377 |
- Processing: columns kept: postal code, place, admin1 name, admin1 code, admin2 name, admin2 code.
  Dropped: FR/DE/IT/ES codes that are not all digits (CEDEX business codes); DE large-customer codes
  (place names of companies or institutions, numeric admin1 code, or empty admin2); ES place names with
  parentheses or commas. Seeded sample of 2,500 rows per country (seed = `derive_seed("postal-sample", country)`).

## gitleaks/gitleaks.toml, gitleaks/LICENSE

- Source: https://github.com/gitleaks/gitleaks, file `config/gitleaks.toml`
- Licence: MIT (copy of the licence in `gitleaks/LICENSE`)
- Revision: tag `v8.30.1`, commit `83d9cd684c87d95d656c1458ef04895a7f1cbd8e`
- SHA-256 of the file: e163e53b9e7e8a8511e77271e2b323ed057759542a6d988258afe3a1fa329caf
- Use: 222 rules; 221 usable for value generation (`pkcs12-file` has only a path pattern). Secret formats are
  drawn uniformly over the usable rules.

## handmade/ (written for AB-1; Apache-2.0, same as the generator)

Short lists of facts and vocabulary, written by the builder:

| file | content |
|---|---|
| email_domains.tsv | public free-mail / ISP domains per country, with draw weights (only the domain; local parts are generated) |
| company_words.tsv, company_suffix.tsv | industry words and legal forms used to build fictional company names and work-mail domains |
| orgs.txt | real company, product and project names (MUST_KEEP `org`) |
| job_titles.tsv | job titles per language (MUST_KEEP `job_title`) |
| honorifics.tsv | honorifics per language (MUST_KEEP `honorific`) |
| gb_bank_codes.txt | four-letter bank identifiers used in GB IBANs (public BIC prefixes) |
| it_belfiore.tsv | cadastral (Belfiore) codes of 20 Italian provincial capitals, used in codici fiscali |
| public_figures.txt | well-known computing figures (AMBIGUOUS `public_figure`) |
| dummy_credentials.txt | classic dummy passwords of test fixtures (AMBIGUOUS `dummy_credential`) |
| role_localparts.txt, role_domains.txt | role mailbox names and real domains for role addresses (AMBIGUOUS `role_address`) |
