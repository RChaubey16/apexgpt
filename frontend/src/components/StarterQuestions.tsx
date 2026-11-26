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

export function StarterQuestions({ onPick, disabled = false }: StarterQuestionsProps) {
  return (
    <ul
      aria-label="Starter questions"
      className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2"
    >
      {STARTER_QUESTIONS.map((s) => (
        <li key={s.question}>
          <button
            type="button"
            onClick={() => onPick(s.question)}
            disabled={disabled}
            className="flex h-full w-full flex-col gap-1 rounded-xl border border-line border-l-accent border-l-2 bg-surface px-4 py-3 text-left transition-colors hover:border-accent hover:bg-raised disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-line disabled:hover:border-l-accent disabled:hover:bg-surface"
          >
            <span className="text-xs font-bold tracking-wider text-accent-text uppercase">
              {s.title}
            </span>
            <span className="text-sm text-soft">{s.question}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
