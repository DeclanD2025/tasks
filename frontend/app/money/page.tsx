import { ModulePlaceholder } from "@/components/module-placeholder";

export default function MoneyPage() {
  return (
    <ModulePlaceholder
      title="Money"
      eyebrow="More · position & runway"
      domain="neutral"
      summary="Monthly position, safe-to-spend, accounts, recent transactions and currency context. Appears on Today only when a warning is worth surfacing."
      owns={["Income, fixed costs, discretionary", "Safe-to-spend & weekly pace", "Accounts & recent transactions", "FX context"]}
      source="Starling (live) + manual accounts"
      state="Built in the backend; numbers are real where a bank import has run, otherwise placeholder."
    />
  );
}
