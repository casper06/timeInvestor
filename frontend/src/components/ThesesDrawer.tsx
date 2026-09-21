import React, { useState, useEffect } from 'react';
import {
  FolderArchive,
  X,
  Plus,
  Trash2,
  UploadCloud,
  CheckCircle2,
  Clock,
  Camera,
  MessageSquare,
  FileText,
} from 'lucide-react';
import {
  fetchTheses,
  createThesis,
  fetchThesisDetail,
  deleteThesis,
  addSnapshot,
  addResearchNote,
} from '../services/api';
import type {
  ThesisSummaryItem,
  ThesisDetailResponse,
  TickerSuggestion,
  MacroSuggestion,
  ForecastResponse,
  TimeSeriesData,
} from '../services/api';

interface ThesesDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  currentPrompt: string;
  currentSummary: string;
  currentTickers: TickerSuggestion[];
  currentMacro: MacroSuggestion[];
  currentRationales: Record<string, string>;
  activeSeriesId: string;
  seriesData: TimeSeriesData | null;
  forecast: ForecastResponse | null;
  horizon: number;
  confidence: number;
  onLoadThesis: (thesis: ThesisDetailResponse) => void;
}

export const ThesesDrawer: React.FC<ThesesDrawerProps> = ({
  isOpen,
  onClose,
  currentPrompt,
  currentSummary,
  currentTickers,
  currentMacro,
  currentRationales,
  activeSeriesId,
  seriesData,
  forecast,
  horizon,
  confidence,
  onLoadThesis,
}) => {
  const [theses, setTheses] = useState<ThesisSummaryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'list' | 'save' | 'detail'>('list');

  // For saving new thesis
  const [saveTitle, setSaveTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [includeSnapshot, setIncludeSnapshot] = useState(true);

  // For viewing detail of selected thesis
  const [selectedDetail, setSelectedDetail] = useState<ThesisDetailResponse | null>(null);
  const [newNoteText, setNewNoteText] = useState('');
  const [addingNote, setAddingNote] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadThesesList();
      if (!saveTitle && currentPrompt) {
        setSaveTitle(currentPrompt.slice(0, 45) + (currentPrompt.length > 45 ? '...' : ''));
      }
    }
  }, [isOpen, currentPrompt]);

  const loadThesesList = async () => {
    setLoading(true);
    try {
      const data = await fetchTheses();
      setTheses(data);
    } catch (err) {
      console.error('Error fetching theses:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveCurrent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!saveTitle.trim() || !currentPrompt.trim()) return;

    setSaving(true);
    try {
      const created = await createThesis({
        title: saveTitle.trim(),
        prompt: currentPrompt,
        summary: currentSummary,
        status: 'Activa',
        tickers: currentTickers,
        macro_series: currentMacro,
        rationales: currentRationales,
      });

      // Optionally save forecast snapshot
      if (includeSnapshot && forecast && seriesData && seriesData.points.length > 0) {
        const lastTs = seriesData.points[seriesData.points.length - 1].timestamp;
        await addSnapshot(created.id, {
          series_id: activeSeriesId,
          cutoff_date: lastTs,
          horizon,
          confidence,
          timestamps: forecast.timestamps,
          projected_values: forecast.values,
          lower_bound: forecast.lower_bound,
          upper_bound: forecast.upper_bound,
          model_name: forecast.model_name,
        });
      }

      await loadThesesList();
      setActiveTab('list');
      setSaveTitle('');
    } catch (err) {
      console.error('Error creating thesis:', err);
      alert('Error al guardar la tesis');
    } finally {
      setSaving(false);
    }
  };

  const handleOpenDetail = async (id: string) => {
    setLoading(true);
    try {
      const detail = await fetchThesisDetail(id);
      setSelectedDetail(detail);
      setActiveTab('detail');
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('¿Estás seguro de eliminar esta tesis guardada?')) return;
    try {
      await deleteThesis(id);
      await loadThesesList();
      if (selectedDetail?.id === id) {
        setActiveTab('list');
        setSelectedDetail(null);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDetail || !newNoteText.trim()) return;

    setAddingNote(true);
    try {
      const added = await addResearchNote(selectedDetail.id, newNoteText.trim());
      setSelectedDetail({
        ...selectedDetail,
        notes: [added, ...selectedDetail.notes],
      });
      setNewNoteText('');
      loadThesesList();
    } catch (err) {
      console.error(err);
    } finally {
      setAddingNote(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm transition-opacity"
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md bg-slate-900 border-l border-slate-800 shadow-2xl flex flex-col text-slate-100">
          {/* Header */}
          <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
            <div className="flex items-center space-x-2.5">
              <FolderArchive className="h-5 w-5 text-cyan-400" />
              <h2 className="text-base font-bold text-white">Repositorio de Tesis</h2>
            </div>
            <button
              onClick={onClose}
              className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Navigation Tabs */}
          <div className="flex border-b border-slate-800 bg-slate-950 text-xs font-medium">
            <button
              onClick={() => setActiveTab('list')}
              className={`flex-1 py-2.5 text-center transition-colors ${
                activeTab === 'list'
                  ? 'border-b-2 border-cyan-500 text-cyan-400 font-bold bg-slate-900/60'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Guardadas ({theses.length})
            </button>
            <button
              onClick={() => setActiveTab('save')}
              className={`flex-1 py-2.5 text-center transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'save'
                  ? 'border-b-2 border-cyan-500 text-cyan-400 font-bold bg-slate-900/60'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Plus className="h-3.5 w-3.5" /> Guardar Actual
            </button>
            {selectedDetail && (
              <button
                onClick={() => setActiveTab('detail')}
                className={`flex-1 py-2.5 text-center transition-colors ${
                  activeTab === 'detail'
                    ? 'border-b-2 border-cyan-500 text-cyan-400 font-bold bg-slate-900/60'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Auditoría / Notas
              </button>
            )}
          </div>

          {/* Content Body */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {/* TAB 1: LIST */}
            {activeTab === 'list' && (
              <div className="space-y-3">
                {loading && (
                  <div className="text-center py-8 text-xs text-cyan-400 font-mono">
                    Cargando repositorio local...
                  </div>
                )}

                {!loading && theses.length === 0 && (
                  <div className="text-center py-12 text-slate-500 text-xs space-y-2">
                    <p>No tienes tesis guardadas aún en SQLite.</p>
                    <button
                      onClick={() => setActiveTab('save')}
                      className="text-cyan-400 hover:underline font-medium"
                    >
                      Guardar la sesión actual
                    </button>
                  </div>
                )}

                {theses.map((t) => (
                  <div
                    key={t.id}
                    className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 hover:border-slate-700 transition-all space-y-2.5 group"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="text-sm font-bold text-slate-200 group-hover:text-cyan-300 transition-colors">
                          {t.title}
                        </h4>
                        <span className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">
                          {t.prompt}
                        </span>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
                          t.status === 'Bajo estrés'
                            ? 'bg-rose-500/10 text-rose-300 border-rose-500/30'
                            : 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                        }`}
                      >
                        {t.status}
                      </span>
                    </div>

                    {/* Tickers Chips */}
                    <div className="flex flex-wrap gap-1">
                      {t.ticker_symbols.map((sym) => (
                        <span
                          key={sym}
                          className="px-1.5 py-0.5 rounded bg-slate-800 text-cyan-400 font-mono text-[10px]"
                        >
                          {sym}
                        </span>
                      ))}
                    </div>

                    {/* Meta info & actions */}
                    <div className="flex items-center justify-between pt-2 border-t border-slate-800/80 text-[11px] text-slate-500">
                      <span className="flex items-center gap-1 font-mono">
                        <Clock className="h-3 w-3" />
                        {t.created_at ? t.created_at.slice(0, 10) : ''}
                      </span>

                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => handleOpenDetail(t.id)}
                          className="text-slate-400 hover:text-white transition-colors"
                          title="Ver auditoría y notas"
                        >
                          <FileText className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(t.id)}
                          className="text-slate-500 hover:text-rose-400 transition-colors"
                          title="Eliminar"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={async () => {
                            const full = await fetchThesisDetail(t.id);
                            onLoadThesis(full);
                            onClose();
                          }}
                          className="px-2.5 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-[11px] transition-colors shadow-sm flex items-center gap-1"
                        >
                          <UploadCloud className="h-3 w-3" /> Cargar
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* TAB 2: SAVE CURRENT */}
            {activeTab === 'save' && (
              <form onSubmit={handleSaveCurrent} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-300">
                    Título de la Tesis
                  </label>
                  <input
                    type="text"
                    value={saveTitle}
                    onChange={(e) => setSaveTitle(e.target.value)}
                    placeholder="Ej. Boom Eléctrico por Centros de Datos"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                    required
                  />
                </div>

                <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 text-xs space-y-2">
                  <div className="text-slate-400 font-medium">Contenido a Persistir:</div>
                  <p className="text-slate-300 italic text-[11px]">"{currentPrompt}"</p>
                  <div className="flex flex-wrap gap-1 pt-1">
                    {currentTickers.map((t) => (
                      <span
                        key={t.symbol}
                        className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 font-mono text-[10px]"
                      >
                        {t.symbol} ({Math.round(t.weight * 100)}%)
                      </span>
                    ))}
                    {currentMacro.map((m) => (
                      <span
                        key={m.series_id}
                        className="px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300 font-mono text-[10px]"
                      >
                        {m.series_id}
                      </span>
                    ))}
                  </div>
                </div>

                {forecast && (
                  <label className="flex items-center space-x-2 text-xs text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={includeSnapshot}
                      onChange={(e) => setIncludeSnapshot(e.target.checked)}
                      className="rounded bg-slate-950 border-slate-700 text-cyan-500 focus:ring-0"
                    />
                    <span>
                      Registrar Snapshot actual de proyección para{' '}
                      <strong className="text-cyan-400">{activeSeriesId}</strong>
                    </span>
                  </label>
                )}

                <button
                  type="submit"
                  disabled={saving || !saveTitle.trim()}
                  className="w-full py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-colors shadow-lg shadow-cyan-600/20 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {saving ? (
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <>
                      <CheckCircle2 className="h-4 w-4" />
                      <span>Guardar en SQLite</span>
                    </>
                  )}
                </button>
              </form>
            )}

            {/* TAB 3: DETAIL / NOTES / SNAPSHOTS */}
            {activeTab === 'detail' && selectedDetail && (
              <div className="space-y-4">
                <div>
                  <button
                    onClick={() => setActiveTab('list')}
                    className="text-xs text-cyan-400 hover:underline mb-2 block"
                  >
                    ← Volver al listado
                  </button>
                  <h3 className="text-sm font-bold text-white">{selectedDetail.title}</h3>
                  <p className="text-xs text-slate-400 mt-1">{selectedDetail.prompt}</p>
                </div>

                {/* Snapshots section */}
                <div className="space-y-2 pt-2 border-t border-slate-800">
                  <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-300">
                    <Camera className="h-3.5 w-3.5 text-amber-400" />
                    <span>Snapshots Registrados ({selectedDetail.snapshots.length})</span>
                  </div>

                  {selectedDetail.snapshots.length === 0 && (
                    <p className="text-[11px] text-slate-500 italic">Sin snapshots aún.</p>
                  )}

                  {selectedDetail.snapshots.map((s) => (
                    <div
                      key={s.id}
                      className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-[11px] space-y-1 font-mono"
                    >
                      <div className="flex justify-between text-slate-400">
                        <span className="text-cyan-300 font-bold">{s.series_id}</span>
                        <span>Corte: {s.cutoff_date}</span>
                      </div>
                      <div className="text-slate-300">
                        Objetivo +{s.horizon}d: ${s.projected_values[s.projected_values.length - 1]?.toFixed(2)} [
                        {s.lower_bound[s.lower_bound.length - 1]?.toFixed(1)} —{' '}
                        {s.upper_bound[s.upper_bound.length - 1]?.toFixed(1)}]
                      </div>
                    </div>
                  ))}
                </div>

                {/* Research Notes section */}
                <div className="space-y-2 pt-2 border-t border-slate-800">
                  <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-300">
                    <MessageSquare className="h-3.5 w-3.5 text-indigo-400" />
                    <span>Notas de Investigación</span>
                  </div>

                  <form onSubmit={handleAddNote} className="flex gap-2">
                    <input
                      type="text"
                      value={newNoteText}
                      onChange={(e) => setNewNoteText(e.target.value)}
                      placeholder="Nueva nota cualitativa..."
                      className="flex-1 px-2.5 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    />
                    <button
                      type="submit"
                      disabled={addingNote || !newNoteText.trim()}
                      className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50"
                    >
                      {addingNote ? '...' : 'Añadir'}
                    </button>
                  </form>

                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {selectedDetail.notes.map((n) => (
                      <div
                        key={n.id}
                        className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-xs space-y-1"
                      >
                        <p className="text-slate-200">{n.note_text}</p>
                        <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                          <span>{n.author}</span>
                          <span>{n.created_at.slice(0, 10)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
