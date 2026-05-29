import { Briefcase } from "lucide-react";
import { Typography } from "@/components/NouiTypography";

export default function VirtualOfficePage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 pb-8 normal-case">
      <header className="flex items-start gap-3">
        <div className="rounded-lg border border-border/60 bg-background-base/40 p-2 text-midground">
          <Briefcase className="h-5 w-5" />
        </div>
        <div>
          <Typography
            mondwest
            className="font-bold text-[1.1rem] tracking-[0.05em] uppercase text-midground"
          >
            Dashboard
          </Typography>
          <p className="mt-1 text-xs text-muted-foreground">
            Placeholder — feature content lands here.
          </p>
        </div>
      </header>
    </div>
  );
}
