import streamlit as st
import pandas as pd
from io import StringIO
from utils.function_utils import _map, nth, _filter, _contains, compose
import utils.function_utils as od
import itertools
import textwrap

st.title("Import Banking")

def odfilter(*args, **kwargs):
	filters = args[1].copy()
	return od._filter_(args[0], filters)

def extract_data_from(releve):
	releve_headers = list(itertools.filterfalse(lambda x: x[1].startswith('Unnamed'),enumerate(releve.columns.values)))
	releve_headers.append((len(releve.columns), 'xxx'))
	hh = list(itertools.pairwise(_map(nth(0), releve_headers)))
	rows = releve.fillna(0).values.tolist()
	raw_rows = []
	for r in rows:
		raw_rows.append(_map(lambda x:r[x[0]:x[1]],hh))
	result =[]
	for r in raw_rows:
		rresult=[]
		for row in r:
			rresult.append(odfilter(row, [od._neq(0)]))
		result.append(rresult)
	return od._filter(lambda x: any(map(lambda y: len(y)>0,x)), result)

def get_bank_statement_values(recent_rows):
	row_values=[]
	def assign_partner(row):
		debiteur = row.Debiteur if hasattr(row, 'Debiteur') else ''
		beneficiaire = row.Beneficiaire if hasattr(row, 'Beneficiaire') else ''
		if len(debiteur)>0:
			return debiteur
		elif len(beneficiaire)>0:
			return beneficiaire
		else:
			return ''
	
	for row in recent_rows.itertuples():
		if hasattr(row, 'Libelle'):
			odoo_notes = " - ".join([row.Libelle, row.Reference, *row.info])
		elif hasattr(row, 'Reference'):
			odoo_notes = " - ".join([row.Reference, *row.info])
		else:
			odoo_notes = ""
		row_values.append([row.virdate, row.ref, assign_partner(row), row.debit, row.credit, odoo_notes])
	return row_values

def get_odoo_values(row_values, assignment_file='bank_partner_mapping.csv'):
	def sign_amount(row):
		if row[3] >0:
			return -row[3]
		else:
			return row[4]
	bp_map = pd.read_csv(assignment_file, sep=';').fillna(False)
	bank_bp_dict = {r.bank_partner:r.choice for r in bp_map.itertuples()}
	odoo_values=[]
	for r in row_values:
		partner_name=''
		debiteur = r[2]
		if debiteur in bank_bp_dict:
			corresponding = bank_bp_dict[debiteur]
			partner_name = corresponding if corresponding else ''
		odoo_values.append([r[0],partner_name,sign_amount(r),f"{r[1]} {r[2]} # {textwrap.shorten(r[5],width=35,placeholder='...')}",r[5],''])
	return odoo_values

def test_filter_row_elements(rows):
	result = {}
	first_row = rows[0]
	result['date']=first_row[0][0]
	result['ref']=first_row[2][0]
	result['debit']= first_row[5][0] if len(first_row[5])>0 else 0
	result['credit']=first_row[-1][0] if len(first_row[-1])>0 else 0
	for r in _filter(compose(_contains('Info'), nth(0)), rows[1:]):
		splitted = r[1].split(':')
		label = splitted[0]
		value = ":".join(_map(lambda x:x.strip(),splitted[1:]))
		if label == 'Info Compl':
			if 'info' not in result:
				result['info'] = []
			result['info'].append(value)
		else:
			result[label]=value
	return result

def read_file(file):
	headers_row_offset=13
	releve = pd.read_excel(file, sheet_name=0, skiprows=headers_row_offset)
	bank_data = extract_data_from(releve)
	bloc_indexes = list(itertools.pairwise(_map(nth(0),od._filter(lambda r: len(r[1][0])>0, enumerate(bank_data)))))
	extracted=[]
	for bloc in bloc_indexes:
		extracted.append(_map(lambda x: x[1] if x[0]==0 else list(itertools.chain(*x[1])),enumerate(bank_data[bloc[0]:bloc[1]])))
	
	recu_rows = pd.DataFrame(_map(test_filter_row_elements, extracted)).fillna('').to_dict(orient='records')
	recent_rows = pd.DataFrame(recu_rows).fillna('')
	recent_rows['virdate'] = [r.date.date().strftime("%Y-%m-%d") for r in recent_rows.itertuples()]
	recent_rows['ref'] = [" ".join(r.ref.split(' ')[0:2]) for r in recent_rows.itertuples()]
	odoo_bank_stmt_fields=['date', 'partner_id', 'amount', 'payment_ref', 'narration', 'statement_id']
	odoo_values = get_odoo_values(get_bank_statement_values(recent_rows))
	total_row = _filter(compose(od._eq('TOTAL'), od.nth(16)), releve.values.tolist())[0]
	total = _filter(lambda x: x==x, total_row)
	return pd.DataFrame([{k:v for k,v in zip(odoo_bank_stmt_fields, values)} for values in odoo_values]), total
uploaded_file = st.file_uploader("Choose a bank file")
if uploaded_file is not None:

	# Can be used wherever a "file-like" object is accepted:
	dataframe, total = read_file(uploaded_file)
	st.write(dataframe)
	st.write('Debit', dataframe.query("amount<0").amount.sum())
	st.write('Credit', dataframe.query("amount>0").amount.sum())
	st.write('Totals in file', total)
