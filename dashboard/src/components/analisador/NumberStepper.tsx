import { ChevronUp, ChevronDown } from 'lucide-react';

interface NumberStepperProps {
  value: number | '';
  onChange: (value: number | '') => void;
  step?: number;
  min?: number;
  max?: number;
  placeholder?: string;
  ariaLabel?: string;
  compacto?: boolean;
}

export function NumberStepper({
  value,
  onChange,
  step = 1,
  min,
  max,
  placeholder,
  ariaLabel,
  compacto = true,
}: NumberStepperProps) {
  const clamp = (n: number) => {
    let v = n;
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    return v;
  };

  const incrementar = (delta: number) => {
    const atual = value === '' ? 0 : value;
    onChange(clamp(atual + delta));
  };

  return (
    <div className="analisador-stepper">
      <input
        className={`analisador-input analisador-stepper-input${compacto ? ' analisador-input-compacto' : ''}`}
        type="number"
        value={value}
        placeholder={placeholder}
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      />
      <div className="analisador-stepper-btns">
        <button type="button" tabIndex={-1} aria-label="Aumentar" onClick={() => incrementar(step)}>
          <ChevronUp size={11} strokeWidth={3} />
        </button>
        <button type="button" tabIndex={-1} aria-label="Diminuir" onClick={() => incrementar(-step)}>
          <ChevronDown size={11} strokeWidth={3} />
        </button>
      </div>
    </div>
  );
}
