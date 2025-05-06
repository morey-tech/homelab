---
# https://adr.github.io/madr/decisions/adr-template.html
# These are optional elements. Feel free to remove any of them.
status: "{proposed | rejected | accepted | deprecated | … | superseded by [ADR-0005](0005-example.md)}"
date: {YYYY-MM-DD when the decision was last updated}
deciders: {list everyone involved in the decision}
consulted: {list everyone whose opinions are sought (typically subject-matter experts); and with whom there is a two-way communication}
informed: {list everyone who is kept up-to-date on progress; and with whom there is a one-way communication}
---
# {short title of solved problem and solution}

## Context and Problem Statement
<!-- {Describe the context and problem statement, e.g., in free form using two to three sentences or in the form of an illustrative story.
 You may want to articulate the problem in form of a question and add links to collaboration boards or issue management systems.} -->
IP addresses are hard to remember, however DNS addresses are easy to recall. How do we server DNS addresses for hosts on the network?

<!-- This is an optional element. Feel free to remove. -->
## Decision Drivers
<!-- * {decision driver 1, e.g., a force, facing concern, …} -->
* DNS servers needs to be highly-available to make them reliable enough to use for configuration in services. (e.g. to reference the NAS using the DNS, the DNS server needs to be reliable)
* The DNS server will be relied on by non-homelab clients (e.g. laptops, phones), so to avoid coupling the homelab hypervisor host (`quasar`) the DNS servers (or atleast one of them) should be separate from it.
* The DNS server should be able to be programtically updated using IaC (i.e. Terraform or Ansible).
* Specific domains can be served by other DNS servers if they meet the other criteria.

## Considered Options
<!-- * {title of option 1} -->
<!-- * … numbers of options can vary -->
* pfSense as the (primary) DNS server.
* Raspberry Pi running DNSMasq, updated using the Hashicorp [DNS provider](https://registry.terraform.io/providers/hashicorp/dns/latest/docs).
* Cloudflare DNS, updated using Terraform [cloudflare provider](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs).
* Raspberry Pi running [PowerDNS](https://www.powerdns.com/), configured using [external-dns](https://github.com/kubernetes-sigs/external-dns?tab=readme-ov-file) (running in Kubernetes).
  * alternative DNS server (secondary or primary) could [run in Kubernetes](https://github.com/cdwv/powerdns-helm).
## Decision Outcome

Chosen option: "{title of option 1}", because
{justification. e.g., only option, which meets k.o. criterion decision driver | which resolves force {force} | … | comes out best (see below)}.

<!-- This is an optional element. Feel free to remove. -->
### Consequences

* Good, because {positive consequence, e.g., improvement of one or more desired qualities, …}
* Bad, because {negative consequence, e.g., compromising one or more desired qualities, …}
* … <!-- numbers of consequences can vary -->

<!-- This is an optional element. Feel free to remove. -->
### Confirmation

{Describe how the implementation of/compliance with the ADR is confirmed. E.g., by a review or an ArchUnit test.
 Although we classify this element as optional, it is included in most ADRs.}

<!-- This is an optional element. Feel free to remove. -->
## Pros and Cons of the Options

### {title of option 1}

<!-- This is an optional element. Feel free to remove. -->
{example | description | pointer to more information | …}

* Good, because {argument a}
* Good, because {argument b}
<!-- use "neutral" if the given argument weights neither for good nor bad -->
* Neutral, because {argument c}
* Bad, because {argument d}
* … <!-- numbers of pros and cons can vary -->

### {title of other option}

{example | description | pointer to more information | …}

* Good, because {argument a}
* Good, because {argument b}
* Neutral, because {argument c}
* Bad, because {argument d}
* …

<!-- This is an optional element. Feel free to remove. -->
## More Information

{You might want to provide additional evidence/confidence for the decision outcome here and/or
 document the team agreement on the decision and/or
 define when/how this decision the decision should be realized and if/when it should be re-visited.
Links to other decisions and resources might appear here as well.}