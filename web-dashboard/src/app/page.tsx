import { AuroraBackground } from "@/components/aurora-background";
import { Dashboard } from "@/components/dashboard";

// Server Component shell — interactive/animated parts live in <Dashboard /> (client leaf).
export default function Home() {
  return (
    <>
      <AuroraBackground />
      <Dashboard />
    </>
  );
}
