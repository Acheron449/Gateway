'use client';
import { useState } from 'react';
import { MainChart } from '@/components/charts/MainChart';
import { AssetSelector } from '@/components/features/AssetSelector';
import { NewsTerminal } from '@/components/features/NewsTerminal'; // <-- add this
import { useLivePrice } from '@/hooks/useLivePrice';

const { price, change, connected } = useLivePrice(selectedTicker);

const WATCHLIST = [
  { symbol: 'AAPL', name: 'Apple Inc.', type: 'STOCK', change: 1.2 },
  { symbol: 'TSLA', name: 'Tesla, Inc.', type: 'STOCK', change: -2.4 },
  { symbol: 'BTC/USD', name: 'Bitcoin', type: 'CRYPTO', change: 0.8 },
  { symbol: 'NVDA', name: 'Nvidia Corp.', type: 'STOCK', change: 4.1 },
];

// mock news (replace later with API)
const MOCK_NEWS = [
  { id: 1, title: 'Apple hits new highs', sentiment: 'positive' },
  { id: 2, title: 'Tesla faces production delays', sentiment: 'negative' },
];

export default function Dashboard() {
  const [selectedTicker, setSelectedTicker] = useState('AAPL');

  return (
    <div className="flex h-screen w-screen bg-[#0d1117] text-white overflow-hidden">
      
      {/* 1. LEFT: Sidebar */}
      <AssetSelector 
        assets={WATCHLIST} 
        selectedTicker={selectedTicker} 
        onSelect={setSelectedTicker} 
      />

      {/* 2. CENTER: Main Area */}
      <main className="flex-1 flex flex-col min-w-0 border-r border-gray-800">
        
        {/* Header */}
        <header className="h-14 border-b border-gray-800 flex items-center px-6 justify-between">
        <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold tracking-tight">
            RefineQuant <span className="text-blue-500">v1</span>
            </h1>

            <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-400">{selectedTicker}</span>

            <span className="font-mono">
                {price !== null ? `$${price.toFixed(2)}` : "..."}
            </span>

            {change !== null && (
                <span className={change >= 0 ? "text-green-400" : "text-red-400"}>
                {change >= 0 ? "+" : ""}
                {change.toFixed(2)}%
                </span>
            )}

            {/* connection indicator */}
            <span
                className={`text-xs ${
                connected ? "text-green-500" : "text-red-500"
                }`}
            >
                {connected ? "LIVE" : "OFFLINE"}
            </span>
            </div>
        </div>

        <div className="text-sm text-gray-400">
            Server Status:{" "}
            <span className={connected ? "text-green-500" : "text-red-500"}>
            {connected ? "Online" : "Disconnected"}
            </span>
        </div>
        </header>
        

        {/* Chart */}
        <div className="flex-1 p-6 overflow-hidden">
          <MainChart 
            key={selectedTicker} 
            ticker={selectedTicker} 
            initialData={[]} 
          />
        </div>

        {/* Bottom Panel */}
        <div className="h-40 border-t border-gray-800 p-4 text-xs font-mono text-gray-500">
          System Log: Signal generated for {selectedTicker}...
        </div>
      </main>

      {/* 3. RIGHT: News Panel */}
      <div className="w-80">
        <NewsTerminal newsItems={MOCK_NEWS} />
      </div>

    </div>
  );
}