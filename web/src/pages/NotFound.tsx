import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { EmptyState, Page } from "../components/ui";
import { useTr } from "../i18n";

/** Any address the app does not know: say so and offer the way back instead of a blank page. */
export function NotFound() {
  const tr = useTr();
  return (
    <Page>
      <div className="mx-auto mt-16 max-w-lg">
        <EmptyState
          icon={<Compass size={32} />}
          title={tr("Такої сторінки немає", "This page does not exist")}
          text={tr("Можливо, посилання застаріло або в адресі помилка.", "The link may be out of date, or the address has a typo.")}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link to="/" className="bg-gradient-brand inline-flex h-9 items-center rounded-lg px-4 text-sm font-medium text-white hover:opacity-90">
                {tr("На головну", "Go home")}
              </Link>
              <Link to="/explore" className="inline-flex h-9 items-center rounded-lg border border-[var(--glass-border)] px-4 text-sm font-medium text-foreground hover:bg-default">
                {tr("Почати розслідування", "Start an investigation")}
              </Link>
            </div>
          }
        />
      </div>
    </Page>
  );
}
