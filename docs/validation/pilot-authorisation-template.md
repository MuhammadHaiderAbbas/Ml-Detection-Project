# Pilot authorisation (template)

> **This is a template, not legal advice.** The organisation's legal and data-protection staff must review
> and adapt it. Nothing in the pilot starts until it is signed.

**Between:** ______________________ ("the Organisation")
**and:** Muhammad Haider Abbas ("the Developer"), developer of Adaptive IDS

**1. Purpose.** To evaluate the Adaptive IDS software for triaging network-flow alerts, as described in
the pilot plan dated ________. No other purpose.

**2. Systems and data in scope**
- Network segment(s): ______________________
- Data: network-flow records (metadata: addresses, ports, protocol, timing and volume statistics) exported
  by the Organisation from ______________________. **No packet payloads.**
- Period of data: from ________ to ________.

**3. Who handles the data**
- The software runs on the Organisation's machine: ______________________ (location or asset ID).
- Only these people may access the software or data: ______________________.
- The Developer has **no** access to the data, unless this box is ticked ☐ and the access method, people
  and supervision are described here: ______________________.

**4. Data stays inside the Organisation.** No data, extracts, screenshots of records, models trained on the
data, or logs that contain addresses leave the Organisation. Aggregate results (counts, rates, survey
scores) leave only in a report the Organisation has approved.

**5. Lawful basis and notices.** The Organisation confirms that it has a lawful basis for processing the
data for this purpose. It confirms that it has carried out any data-protection assessment it requires.
Reference: ______________________.

**6. Security**
- Access is restricted to the named people, using individual accounts.
- The database is on encrypted storage, and backups are kept only on: ______________________.
- The software listens only on the local machine, or behind the Organisation's TLS reverse proxy.

**7. No interference.** The software is read-only with respect to the network. It runs alongside the
Organisation's existing tools and does not replace any monitoring or response duty.

**8. Retention and deletion.** Data is kept for no longer than ________ days. At the end of the pilot, or
when this authorisation is withdrawn, all data, backups and derived models are deleted within ________
days, and the Organisation confirms the deletion in writing.

**9. Withdrawal.** The Organisation may withdraw this authorisation at any time, in writing. The pilot then
stops and section 8 applies.

**10. Confidentiality and publication.** The Developer may not name the Organisation or publish results
without the Organisation's written approval of the exact text.

**11. Software.** The software is provided for evaluation under its licence (all rights reserved), without
warranty and without charge, unless agreed otherwise in writing.

| | Organisation | Developer |
|---|---|---|
| Name | | Muhammad Haider Abbas |
| Role | | |
| Authority over the network and data | ☐ confirmed | — |
| Signature | | |
| Date | | |
