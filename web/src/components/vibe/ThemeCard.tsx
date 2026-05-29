import { Check } from "lucide-react";
import { Typography } from "@/components/NouiTypography";
import { cn } from "@/lib/utils";

export interface ThemeOption {
  name: string;
  label: string;
  description: string;
  imageUrl: string;
}

interface Props {
  theme: ThemeOption;
  selected: boolean;
  onSelect: () => void;
}

export function ThemeCard({ theme, selected, onSelect }: Props) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "group relative flex flex-col overflow-hidden rounded-lg border bg-background-base/40 text-left",
        "shadow-xs transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-midground/40",
        selected
          ? "border-midground/80 ring-2 ring-midground/30"
          : "border-border/60 hover:border-midground/40 hover:shadow-sm",
      )}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-background-base/60">
        <img
          src={theme.imageUrl}
          alt={theme.label}
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover"
        />
        {selected && (
          <span className="absolute right-2 top-2 inline-flex h-5 w-5 items-center justify-center rounded-full bg-midground text-background">
            <Check className="h-3 w-3" strokeWidth={3} />
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1 px-3 py-3">
        <Typography
          mondwest
          className="text-[0.9rem] font-bold uppercase tracking-[0.05em] text-midground"
        >
          {theme.label}
        </Typography>
        <p className="text-xs leading-snug text-muted-foreground/80">
          {theme.description}
        </p>
        <p className="mt-1 font-mono text-[0.6rem] uppercase tracking-wider text-muted-foreground/50">
          {theme.name}
        </p>
      </div>
    </button>
  );
}
