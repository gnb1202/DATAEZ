import { cn } from "@/lib/utils";

type DataEzLogoProps = {
  symbolOnly?: boolean;
  tone?: "auto" | "dark" | "light";
  className?: string;
};

function MarkPaths() {
  return (
    <>
      <path
        d="M10 11H37C47.5 11 53 16.5 53 27V37C53 47.5 47.5 53 37 53H10"
        fill="none"
        stroke="var(--brand-logo-accent)"
        strokeWidth="10"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M16 32H36"
        fill="none"
        stroke="var(--brand-logo-accent)"
        strokeWidth="10"
        strokeLinecap="round"
      />
    </>
  );
}

export function DataEzLogo({ symbolOnly = false, tone = "auto", className }: DataEzLogoProps) {
  const palette =
    tone === "dark"
      ? "dataez-logo--dark"
      : tone === "light"
        ? "dataez-logo--light"
        : "dataez-logo--auto";

  if (symbolOnly) {
    return (
      <svg
        viewBox="0 0 64 64"
        role="img"
        aria-label="DATA:EZ"
        className={cn("shrink-0", palette, className)}
      >
        <MarkPaths />
      </svg>
    );
  }

  return (
    <svg
      viewBox="0 0 320 64"
      role="img"
      aria-label="DATA:EZ"
      className={cn("shrink-0", palette, className)}
    >
      <MarkPaths />
      <g fill="currentColor" transform="translate(78 53) scale(.056 -.056)">
        <path d="M91 0H302C520 0 660 125 660 373C660 624 520 740 294 740H91ZM239 119V622H285C424 622 509 554 509 373C509 193 424 119 285 119Z" />
        <path transform="translate(714)" d="M490 0H645L407 740H233L-4 0H146L198 190H438ZM230 305 252 386C275 463 296 547 315 628H319C342 548 361 463 384 386L406 305Z" />
        <path transform="translate(1355)" d="M238 0H386V617H596V740H30V617H238Z" />
        <path transform="translate(1980)" d="M490 0H645L407 740H233L-4 0H146L198 190H438ZM230 305 252 386C275 463 296 547 315 628H319C342 548 361 463 384 386L406 305Z" />
      </g>
      <circle cx="236" cy="27" r="3.7" fill="var(--brand-logo-accent)" />
      <circle cx="236" cy="42" r="3.7" fill="var(--brand-logo-accent)" />
      <g fill="currentColor" transform="translate(247 53) scale(.056 -.056)">
        <path d="M91 0H556V124H239V322H499V446H239V617H545V740H91Z" />
        <path transform="translate(615)" d="M43 0H573V124H225L569 652V740H76V617H388L43 89Z" />
      </g>
    </svg>
  );
}
