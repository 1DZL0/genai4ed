/** The idea, drawn: a teacher, one class agent, and students, with what passes between them. */

const INK = "var(--ink)";
const PENCIL = "var(--pencil)";
const SHEET = "var(--sheet)";

function Person({ x, y, size = 1 }: { x: number; y: number; size?: number }) {
  const r = 16 * size;
  return (
    <g
      transform={`translate(${x} ${y})`}
      fill={SHEET}
      stroke={INK}
      strokeWidth={2}
    >
      <circle cx={0} cy={0} r={r} />
      <path
        d={`M ${-2.2 * r} ${3.4 * r} a ${2.2 * r} ${2.2 * r} 0 0 1 ${4.4 * r} 0 z`}
      />
    </g>
  );
}

function Agent({ x, y }: { x: number; y: number }) {
  return (
    <g
      transform={`translate(${x} ${y})`}
      fill={SHEET}
      stroke={INK}
      strokeWidth={2}
    >
      <line x1={0} y1={-40} x2={0} y2={-26} />
      <circle cx={0} cy={-44} r={4} fill={INK} />
      <rect x={-38} y={-26} width={76} height={62} rx={14} />
      <circle cx={-14} cy={2} r={5} fill={INK} stroke="none" />
      <circle cx={14} cy={2} r={5} fill={INK} stroke="none" />
      <path d="M -12 18 q 12 10 24 0" fill="none" strokeLinecap="round" />
      <rect x={-50} y={44} width={100} height={22} rx={11} />
    </g>
  );
}

export function Framework() {
  return (
    <figure aria-labelledby="framework-title" className="w-full max-w-4xl">
      <svg
        viewBox="0 0 900 320"
        role="img"
        aria-labelledby="framework-title"
        className="h-auto w-full font-sans"
      >
        <title id="framework-title">
          The teacher tells the class agent what to teach; the agent teaches
          each student in their own conversation and tells the teacher who needs
          them.
        </title>
        <defs>
          <marker
            id="head"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill={INK} />
          </marker>
        </defs>

        {/* teacher */}
        <Person x={110} y={120} size={1.5} />
        <text
          x={110}
          y={225}
          textAnchor="middle"
          fontSize="20"
          fontWeight="600"
          fill={INK}
          fontFamily="var(--font-serif)"
        >
          Teacher
        </text>

        {/* agent */}
        <Agent x={450} y={130} />
        <text
          x={450}
          y={225}
          textAnchor="middle"
          fontSize="20"
          fontWeight="600"
          fill={INK}
          fontFamily="var(--font-serif)"
        >
          Class agent
        </text>

        {/* students */}
        <Person x={730} y={60} />
        <Person x={800} y={130} />
        <Person x={730} y={200} />
        <text
          x={770}
          y={290}
          textAnchor="middle"
          fontSize="20"
          fontWeight="600"
          fill={INK}
          fontFamily="var(--font-serif)"
        >
          Students
        </text>

        {/* teacher and agent */}
        <path
          d="M 190 110 L 385 110"
          fill="none"
          stroke={INK}
          strokeWidth={2}
          markerEnd="url(#head)"
        />
        <text
          x={288}
          y={98}
          textAnchor="middle"
          fontSize="15"
          fill={PENCIL}
          className="hidden sm:block"
        >
          the lesson and the rules
        </text>
        <path
          d="M 385 160 L 190 160"
          fill="none"
          stroke={INK}
          strokeWidth={2}
          markerEnd="url(#head)"
        />
        <text
          x={288}
          y={184}
          textAnchor="middle"
          fontSize="15"
          fill={PENCIL}
          className="hidden sm:block"
        >
          who needs you, the marks
        </text>

        {/* agent and students */}
        <path
          d="M 515 110 C 580 110, 600 70, 690 62"
          fill="none"
          stroke={INK}
          strokeWidth={2}
          markerEnd="url(#head)"
        />
        <path
          d="M 515 130 L 755 130"
          fill="none"
          stroke={INK}
          strokeWidth={2}
          markerEnd="url(#head)"
        />
        <path
          d="M 515 150 C 580 150, 600 190, 690 202"
          fill="none"
          stroke={INK}
          strokeWidth={2}
          markerEnd="url(#head)"
        />
        <text
          x={600}
          y={40}
          textAnchor="middle"
          fontSize="15"
          fill={PENCIL}
          className="hidden sm:block"
        >
          teaches, one to one
        </text>
        <path
          d="M 690 252 C 620 252, 560 210, 510 190"
          fill="none"
          stroke={PENCIL}
          strokeWidth={1.5}
          strokeDasharray="4 4"
          markerEnd="url(#head)"
        />
        <text
          x={620}
          y={280}
          textAnchor="middle"
          fontSize="15"
          fill={PENCIL}
          className="hidden sm:block"
        >
          answers
        </text>
      </svg>
    </figure>
  );
}
