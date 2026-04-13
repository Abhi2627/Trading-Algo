import React, { useState, useEffect, useRef } from 'react';
import { SendHorizonal, MessageSquare, HelpCircle, TrendingUp,
         Briefcase, BookOpen, ShieldAlert, ExternalLink } from 'lucide-react';
import { chat, ChatMessage, ChatResponse } from '../lib/api';
import LoadingSpinner from '../components/LoadingSpinner';

interface ChatMessageWithMeta extends ChatMessage {
  context_used?: string;
  signal_id?: string | null;
}

const Chat: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessageWithMeta[]>([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const suggestions = {
    signals: ["Why did you buy Reliance?","Explain the TCS signal","What drove the BTC sell signal?","Why is confidence low for HDFC?"],
    portfolio: ["How is my portfolio doing?","What is my drawdown?","How much did I make today?","What is my risk mode?"],
    education: ["What is RSI?","How does the RL agent work?","What is the ensemble score?","Explain market regime"]
  };

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isTyping]);

  const handleSend = async (text: string) => {
    if (!text.trim() || isTyping) return;
    const userMsg: ChatMessageWithMeta = { role: 'user', content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput('');
    setIsTyping(true);
    setError(null);
    try {
      const history: ChatMessage[] = messages.map(({ role, content }) => ({ role, content }));
      const response: ChatResponse = await chat(text, history);
      setMessages([...newMessages, { role: 'assistant', content: response.reply, context_used: response.context_used, signal_id: response.signal_id }]);
    } catch (err) {
      setError('Failed to get a response. Please check your connection.');
    } finally {
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(input); }
  };

  const SuggestionSection = ({ title, icon: Icon, items }: { title: string; icon: React.FC<{size:number}>; items: string[] }) => (
    <section>
      <div className="flex items-center gap-2 text-text-secondary text-xs font-bold mb-3 uppercase tracking-tighter"><Icon size={12} />{title}</div>
      <div className="flex flex-wrap gap-2">
        {items.map(s => (<button key={s} onClick={() => handleSend(s)} className="text-left text-[11px] bg-background-elevated hover:bg-background-primary border border-border-default hover:border-accent p-2 rounded-lg text-text-secondary hover:text-accent transition-all leading-tight">{s}</button>))}
      </div>
    </section>
  );

  return (
    <div className="flex h-[calc(100vh-64px)] overflow-hidden -m-8">
      <aside className="w-[280px] bg-background-surface border-r border-border-default flex flex-col p-6 overflow-y-auto">
        <h2 className="text-xs font-bold text-text-muted uppercase tracking-widest mb-6 flex items-center gap-2"><HelpCircle size={14} className="text-accent" />Ask about...</h2>
        <div className="space-y-8">
          <SuggestionSection title="Signals" icon={TrendingUp} items={suggestions.signals} />
          <SuggestionSection title="Portfolio" icon={Briefcase} items={suggestions.portfolio} />
          <SuggestionSection title="Education" icon={BookOpen} items={suggestions.education} />
        </div>
      </aside>

      <main className="flex-1 flex flex-col bg-background-primary">
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-8 space-y-6 scroll-smooth">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto space-y-6 opacity-40">
              <div className="w-16 h-16 bg-accent/10 rounded-2xl flex items-center justify-center"><MessageSquare size={32} className="text-accent" /></div>
              <div><h3 className="text-lg font-bold text-text-primary mb-2">How can I help you?</h3><p className="text-sm text-text-secondary leading-relaxed">Ask me anything about your trading signals, portfolio performance, or how the AI makes decisions.</p></div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="max-w-[80%] space-y-2">
                <div className={`p-4 rounded-2xl text-sm leading-relaxed ${msg.role === 'user' ? 'bg-accent text-white rounded-tr-none' : 'bg-background-surface border border-border-default text-text-secondary rounded-tl-none'}`}>{msg.content}</div>
                {msg.role === 'assistant' && msg.context_used && (
                  <div className="flex items-center gap-3 px-1">
                    <span className={`text-[9px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded ${msg.context_used === 'signal_explanation' ? 'bg-accent/20 text-accent' : msg.context_used === 'portfolio' ? 'bg-amber/20 text-amber' : 'bg-background-elevated text-text-muted'}`}>{msg.context_used.replace('_', ' ')}</span>
                    {msg.signal_id && <button className="flex items-center gap-1 text-[9px] font-bold text-accent hover:underline uppercase">View Signal <ExternalLink size={10} /></button>}
                  </div>
                )}
              </div>
            </div>
          ))}
          {isTyping && (<div className="flex justify-start"><div className="bg-background-surface border border-border-default p-4 rounded-2xl rounded-tl-none"><div className="flex gap-1"><div className="w-1.5 h-1.5 bg-text-muted rounded-full animate-bounce" style={{animationDelay:'0ms'}} /><div className="w-1.5 h-1.5 bg-text-muted rounded-full animate-bounce" style={{animationDelay:'150ms'}} /><div className="w-1.5 h-1.5 bg-text-muted rounded-full animate-bounce" style={{animationDelay:'300ms'}} /></div></div></div>)}
          {error && (<div className="flex justify-center"><div className="bg-red/10 border border-red/20 text-red text-xs font-bold px-4 py-2 rounded-full flex items-center gap-2"><ShieldAlert size={14} />{error}</div></div>)}
        </div>
        <div className="p-8 pt-0">
          <div className="relative max-w-4xl mx-auto">
            <textarea rows={1} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="Ask about a signal, your portfolio, or trading concepts..." disabled={isTyping} className="w-full bg-background-surface border border-border-default focus:border-accent text-text-primary text-sm rounded-2xl py-4 pl-6 pr-16 focus:outline-none transition-all resize-none disabled:opacity-60" />
            <button onClick={() => handleSend(input)} disabled={!input.trim() || isTyping} className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 bg-accent hover:bg-accent-hover disabled:bg-background-elevated text-white rounded-xl flex items-center justify-center transition-all">
              {isTyping ? <LoadingSpinner size="sm" /> : <SendHorizonal size={18} />}
            </button>
          </div>
          <p className="text-[10px] text-text-muted text-center mt-3 uppercase tracking-widest">AI can make mistakes. Always verify critical trading decisions.</p>
        </div>
      </main>
    </div>
  );
};

export default Chat;
