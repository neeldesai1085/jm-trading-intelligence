from pydantic import BaseModel
class InstrumentMappingIn(BaseModel):
    isin:str
    security:str=''
    provider:str
    instrument_key:str
