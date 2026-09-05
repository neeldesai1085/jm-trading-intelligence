from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Float, Date, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

class ImportBatch(Base):
    __tablename__ = 'import_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default='PROCESSING')
    contract_notes_found: Mapped[int] = mapped_column(Integer, default=0)
    contracts_added: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    executions_added: Mapped[int] = mapped_column(Integer, default=0)
    security_rows_added: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ContractNote(Base):
    __tablename__ = 'contract_notes'
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_note: Mapped[str] = mapped_column(String(64), unique=True)
    trade_date: Mapped[date] = mapped_column(Date)
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    settlement_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_note_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annexure_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_qty: Mapped[int] = mapped_column(Integer, default=0)
    sell_qty: Mapped[int] = mapped_column(Integer, default=0)
    gross_buy_value: Mapped[float] = mapped_column(Float, default=0)
    gross_sell_value: Mapped[float] = mapped_column(Float, default=0)
    displayed_brokerage: Mapped[float] = mapped_column(Float, default=0)
    buy_value_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    sell_value_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    market_flow_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    payin_obligation: Mapped[float] = mapped_column(Float, default=0)
    taxable_value: Mapped[float] = mapped_column(Float, default=0)
    stt: Mapped[float] = mapped_column(Float, default=0)
    cgst: Mapped[float] = mapped_column(Float, default=0)
    sgst: Mapped[float] = mapped_column(Float, default=0)
    ugst: Mapped[float] = mapped_column(Float, default=0)
    igst: Mapped[float] = mapped_column(Float, default=0)
    exchange_charges: Mapped[float] = mapped_column(Float, default=0)
    sebi_fees: Mapped[float] = mapped_column(Float, default=0)
    stamp_duty: Mapped[float] = mapped_column(Float, default=0)
    ipft: Mapped[float] = mapped_column(Float, default=0)
    net_amount: Mapped[float] = mapped_column(Float, default=0)

class SecurityLedger(Base):
    __tablename__ = 'security_ledger'
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_note: Mapped[str] = mapped_column(String(64))
    trade_date: Mapped[date] = mapped_column(Date)
    isin: Mapped[str] = mapped_column(String(32))
    security: Mapped[str] = mapped_column(String(255))
    buy_qty: Mapped[int] = mapped_column(Integer, default=0)
    buy_wap: Mapped[float] = mapped_column(Float, default=0)
    buy_brokerage_share: Mapped[float] = mapped_column(Float, default=0)
    buy_wap_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    total_buy_value_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    gross_buy: Mapped[float] = mapped_column(Float, default=0)
    displayed_buy_brokerage: Mapped[float] = mapped_column(Float, default=0)
    sell_qty: Mapped[int] = mapped_column(Integer, default=0)
    sell_wap: Mapped[float] = mapped_column(Float, default=0)
    sell_brokerage_share: Mapped[float] = mapped_column(Float, default=0)
    sell_wap_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    total_sell_value_after_brokerage: Mapped[float] = mapped_column(Float, default=0)
    gross_sell: Mapped[float] = mapped_column(Float, default=0)
    displayed_sell_brokerage: Mapped[float] = mapped_column(Float, default=0)
    net_qty: Mapped[int] = mapped_column(Integer, default=0)
    net_obligation_before_levies: Mapped[float] = mapped_column(Float, default=0)
    __table_args__ = (UniqueConstraint('contract_note','isin','buy_qty','sell_qty','total_buy_value_after_brokerage','total_sell_value_after_brokerage', name='uq_sec'),)

class Execution(Base):
    __tablename__ = 'executions'
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_note: Mapped[str] = mapped_column(String(64))
    trade_date: Mapped[date] = mapped_column(Date)
    order_no: Mapped[str] = mapped_column(String(64))
    order_time: Mapped[str] = mapped_column(String(32))
    trade_no: Mapped[str] = mapped_column(String(64))
    trade_time: Mapped[str] = mapped_column(String(32))
    security: Mapped[str] = mapped_column(String(255))
    exchange: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    market_rate: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint('contract_note','trade_no', name='uq_exec'),)

class MarketQuote(Base):
    __tablename__ = 'market_quotes'
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ltp: Mapped[float | None] = mapped_column(Float, nullable=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class InstrumentMapping(Base):
    __tablename__ = 'instrument_mappings'
    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    security: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(32))
    instrument_key: Mapped[str] = mapped_column(String(128))

class TradeAnnotation(Base):
    __tablename__ = 'trade_annotations'
    id: Mapped[int] = mapped_column(primary_key=True)
    security: Mapped[str] = mapped_column(String(255))
    buy_date: Mapped[date] = mapped_column(Date)
    sell_date: Mapped[date] = mapped_column(Date)
    strategy: Mapped[str] = mapped_column(String(128), default='Unclassified')
    setup: Mapped[str] = mapped_column(String(128), default='')
    regime: Mapped[str] = mapped_column(String(128), default='')
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint('security','buy_date','sell_date', name='uq_trade_annotation'),)
