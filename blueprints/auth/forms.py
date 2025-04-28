from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, ValidationError, EqualTo, Length
from .models import User

class LoginForm(FlaskForm):
    email: StringField = StringField('Email', validators=[DataRequired(), Email()])
    password: PasswordField = PasswordField('Password', validators=[DataRequired()])
    remember: BooleanField = BooleanField('Remember Me')
    submit: SubmitField = SubmitField('Login')

class RegisterForm(FlaskForm):
    username: StringField = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email: StringField = StringField('Email', validators=[DataRequired(), Email()])
    password: PasswordField = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password: PasswordField = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match')])
    submit: SubmitField = SubmitField('Register')
    
    def validate_username(self, username: StringField) -> None:
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already exists. Please choose a different one.')
    
    def validate_email(self, email: StringField) -> None:
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered. Please use a different one or login.')
