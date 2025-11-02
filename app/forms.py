from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired

class SalesForm(FlaskForm):
    pelanggan_id = SelectField('Pelanggan', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Simpan')
