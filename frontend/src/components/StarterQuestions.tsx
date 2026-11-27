/**
 * Starter question cards on an empty chat. Picking one asks it straight away.
 *
 * The questions cover both tools (stats and F1 history) and were checked
 * against the live backend: each one gets a correct, well-formed answer.
 * Keep them to questions the data answers well (no per-season poles, for
 * example; see the Known Issues in docs/archive/v1.0.0-mvp/PROGRESS.md).
 */

export interface StarterQuestion {
  /** Short card title. */
  title: string;
  /** The question sent to the backend. */
  question: string;
}

export const STARTER_QUESTIONS: readonly StarterQuestion[] = [
  {
    title: "Abu Dhabi 2021",
    question: "Explain the 2021 Abu Dhabi Grand Prix controversy",
  },
  {
    title: "Senna vs Prost",
    question: "Tell me about the Senna–Prost rivalry",
  },
  {
    title: "Hunt's 1976 title",
    question: "How did James Hunt win the 1976 title?",
  },
  {
    title: "Most championships",
    question: "Who has won the most World Drivers' Championships?",
  },
  {
    title: "Winningest team",
    question: "Which constructor has won the most races?",
  },
  {
    title: "The 2023 season",
    question: "Who won the most races in the 2023 season?",
  },
];

interface StarterQuestionsProps {
  onPick: (question: string) => void;
  disabled?: boolean;
}

/**
 * Laid out like rows of a timing table, not cards: the short title in a
 * condensed column, the question beside it, rows ruled apart. On phones the
 * title sits above the question.
 */
export function StarterQuestions({ onPick, disabled = false }: StarterQuestionsProps) {
  return (
    <ul
      aria-label="Starter questions"
      className="w-full divide-y divide-line border-y border-line"
    >
      {STARTER_QUESTIONS.map((s) => (
        <li key={s.question}>
          <button
            type="button"
            onClick={() => onPick(s.question)}
            disabled={disabled}
            className="group flex w-full flex-col gap-0.5 px-2 py-3 text-left hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent sm:flex-row sm:items-baseline sm:gap-4"
          >
            <span className="shrink-0 text-base font-semibold text-foreground font-stretch-condensed sm:w-44">
              {s.title}
            </span>
            <span className="text-soft group-hover:text-foreground group-disabled:group-hover:text-soft">
              {s.question}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
