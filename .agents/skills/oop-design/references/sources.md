# Sources and interpretation

Reviewed 2026-09-07. The skill is an original, concise decision guide, not a reproduction of these tutorials or their code. Pattern-specific references are linked next to each entry. Alternatives, rejection criteria, implementation checks, and project workflow guidance are engineering synthesis; the sources do not independently substantiate every recommendation.

- [Refactoring.Guru: What's a design pattern?](https://refactoring.guru/design-patterns/what-is-pattern) supplies the framing of patterns as adaptable design concepts rather than ready-made code. Its individual pattern pages supply more specific mechanisms, tradeoffs, and comparisons; those pages are linked in the three family references.
- [JavaTechOnline: When to Use Which Design Pattern?](https://javatechonline.com/when-to-use-which-design-pattern-23-gof-pattern/) supplies the requested coverage of all 23 GoF patterns and an applicability-oriented perspective, including Interpreter. Its scenarios are illustrative rather than sufficient design requirements.
- [GeeksforGeeks: Design Patterns in Object-Oriented Programming](https://www.geeksforgeeks.org/system-design/design-patterns-in-object-oriented-programming-oop/) supplies a brief overview of creational, structural, and behavioral categories. It is an introductory overview, not detailed support for the individual tradeoffs.

## Qualifications applied

- Runtime type selection alone does not establish GoF Factory Method. The subclass creation hook distinguishes it from a simple factory function.
- Singleton scope must be explicit; uniqueness within a process does not coordinate multiple services or imply thread-safe operations.
- Prototype copying is not necessarily deep or cheaper than construction. Define copy semantics and measure performance when relevant.
- A pattern can reduce one kind of coupling while introducing another. Visitor favors adding operations over adding element types; Abstract Factory favors new families over new product categories.
- Builder, State, and Chain of Responsibility are options rather than automatic responses to optional arguments, enums, or conditionals.
- Notifications, queues, undo, and wrappers do not by themselves supply durability, distributed transactions, idempotency, or exactly-once effects.

The skill is self-contained for ordinary use. Follow source links when a deeper explanation is needed; verify language- or framework-specific APIs against their own documentation when implementing them.
