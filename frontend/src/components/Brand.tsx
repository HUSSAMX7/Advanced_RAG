export default function Brand({ large = false }: { large?: boolean }) {
  return (
    <span className={`brand-symbol ${large ? 'large' : ''}`} aria-hidden="true">
      <svg viewBox="0 0 64 64" fill="none">
        <ellipse cx="32" cy="32" rx="22" ry="10" transform="rotate(-40 32 32)" />
        <ellipse cx="32" cy="32" rx="22" ry="10" transform="rotate(40 32 32)" />
        <circle cx="32" cy="32" r="4" />
      </svg>
    </span>
  )
}
