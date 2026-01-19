export interface ProductStats {
    id: number;
    name: string;
    avg24: number;
    avg25: number;
    total: number;
}

export interface MonthlyData {
    year: number;
    name: string;
}

export interface DashboardData {
    rows: any[][];
    monthly: MonthlyData[];
    maps: {
        c: string[];
        s: string[];
        m: string[];
        d: string[];
        r: string[];
    };
    updated_at?: string;
}

export interface AggregatedStats {
    rev: number;
    qty: number;
    cnt: number;
    monthly: Record<number, number>;
    mfrs: Record<number, number>;
    descs: Record<number, number>;
    products: Record<number, number>;
}

export interface TrendItem {
    id: number;
    name: string;
    rev24: number;
    rev25: number;
    diff: number;
    up: boolean;
}
