# Documentation authority

When repository documents differ, apply this order:

1. `SPEC.md`: product and behavioral contract.
2. `ARCHITECTURE.md`: component boundaries and deployment design.
3. `COMPLIANCE.md`: control mapping and adopter-owned regulatory interpretation.
4. `README.md`: operator and contributor quick start.
5. `DEMO.md`, runbooks, FAQs and other supporting guides.

`docs/practices-audit.md` records evidence and gaps. It does not
override the current contract. A behavioral change updates the highest applicable document and
reconciles lower layers in the same change.
