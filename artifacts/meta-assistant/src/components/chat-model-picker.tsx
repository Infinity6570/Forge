import { Zap } from 'lucide-react';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select';

export type ModelPickerGroup = { id: string; label: string; items: readonly { id: string; name: string }[] };
export type ModelPickerBenchmark = { rating?: number | null; rank?: number | null };
type Props = {
  value: string;
  onChange: (value: string) => void;
  configuredLabel: string;
  lastUsedLabel: string | null;
  currentSessionLabel?: string;
  groups: ModelPickerGroup[];
  benchmarkRatings?: Record<string, ModelPickerBenchmark>;
};

export function ChatModelPicker({ value, onChange, configuredLabel, lastUsedLabel, currentSessionLabel, groups, benchmarkRatings = {} }: Props) {
  const selectedParts = value.split('|');
  const hasListedSelection = selectedParts.length === 3 && groups.some((group) =>
    group.id === selectedParts[1] && group.items.some((item) => item.id === selectedParts[2]),
  );
  return <Select value={value} onValueChange={onChange}>
    <SelectTrigger className="composer-model model-trigger" aria-label="Task model" data-testid="select-task-model">
      <Zap size={12} aria-hidden="true" /><span className="model-trigger-value"><SelectValue /></span>
    </SelectTrigger>
    <SelectContent className="model-menu" position="popper" align="end" sideOffset={6} collisionPadding={12}>
      <SelectGroup>
        <SelectItem value="configured" className="model-menu-item">{configuredLabel}</SelectItem>
        <SelectItem value="last-used" disabled={!lastUsedLabel} className="model-menu-item">Last used · {lastUsedLabel ?? 'unavailable'}</SelectItem>
        <SelectSeparator className="model-menu-sep" />
        <SelectLabel className="model-menu-label">AUTONOMOUS ROUTING</SelectLabel>
        <SelectItem value="auto-gemini" className="model-menu-item">Gemini: Auto Select</SelectItem>
        <SelectItem value="auto-claude" className="model-menu-item">Claude: Auto Select</SelectItem>
        <SelectItem value="auto-openai" className="model-menu-item">OpenAI: Auto Select</SelectItem>
        <SelectItem value="auto-global" className="model-menu-item">Global Auto Select</SelectItem>
        {!hasListedSelection && selectedParts.length === 3 && selectedParts[0] === 'direct' && <SelectItem value={value} className="model-menu-item">{currentSessionLabel ?? selectedParts[2]}</SelectItem>}
      </SelectGroup>
      {groups.map((group) => <SelectGroup key={group.id}>
        <SelectSeparator className="model-menu-sep" />
        <SelectLabel className="model-menu-label">{group.label}</SelectLabel>
        {group.items.map((item) => {
          const benchmark = benchmarkRatings[item.id];
          const benchmarkLabel = typeof benchmark?.rating === 'number'
            ? `BLM ${benchmark.rating.toFixed(1)}`
            : typeof benchmark?.rank === 'number'
              ? `BLM #${benchmark.rank}`
              : null;
          return <SelectItem key={`${group.id}:${item.id}`} value={`direct|${group.id}|${item.id}`} className="model-menu-item">
            <span className="model-menu-item-name">{item.name}</span>
            {benchmarkLabel && <span className="model-benchmark-badge" title="BenchLM coding ranking">{benchmarkLabel}</span>}
          </SelectItem>;
        })}
      </SelectGroup>)}
    </SelectContent>
  </Select>;
}
