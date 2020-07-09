#!/usr/bin/env python
import pandas as pd
import sys
import argparse
from sklearn.impute import KNNImputer
from sklearn.preprocessing import PolynomialFeatures
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.model_selection import StratifiedKFold
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_curve, auc, accuracy_score
import numpy as np
from scipy import interp
import joblib
import os
import matplotlib.pyplot as plt
from tqdm import tqdm
from keras.models import Sequential
from keras.layers import Dense
from keras.optimizers import SGD

def perform_gridsearch(X, y, categorical, threads):
    kneighbors = [6]#np.arange(2, 6, 1)
    degrees = [3]#np.arange(2, 5, 1)
    n_components = [10, 100, 400, 600, 800]#np.arange(1, 7, 1)
    n_splits = 10
    methods = ['RF', 'LR', 'SVC']#, 'NN']
    #categorical = 'education male currentSmoker prevalentStroke prevalentHyp diabetes'.split(' ')
    best_acc = 0.0
    # Split data in train and test set   
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    nr_combinations = len(kneighbors) * len(degrees) * len(n_components) * len(methods)
    with tqdm(total=nr_combinations) as pbar:
        for method in methods:
            for d in degrees:
                for k in kneighbors:
                    for n in n_components:
                        # prepare training data
                        preprocessing_train = Preprocessing(X_train, y_train, k, d, categorical, method)
                        preprocessed_data_train = preprocessing_train()
                        dim_reduction_train = DimensionalityReduction(preprocessed_data_train, n)
                        reduced_data_train, components_train, variance_ratio = dim_reduction_train()
    
                        #prepare test data
                        preprocessing_test = Preprocessing(X_test, y_test, k, d, categorical, method)
                        preprocessed_data_test = preprocessing_test()
                        dim_reduction_test = DimensionalityReduction(preprocessed_data_test, n)
                        reduced_data_test, _, _ = dim_reduction_test()
                        
                        classification = Classification(reduced_data_train, y_train, method, n_splits, threads)
                        model, statistics = classification()
                        accuracy = classification.evaluate_model(reduced_data_test, y_test, model)
                        # keep track of best model
                        if accuracy > best_acc:
                            best_acc = accuracy
                            params_best_acc = [method, k, d, n]
                            best_model = model
                            best_statistics = statistics
                        pbar.update(1)
    print(f'Params best ACC:\nMethod: {params_best_acc[0]}\nk: {params_best_acc[1]}\ndegree: {params_best_acc[2]}\nn_components: {params_best_acc[3]}\nACC: {best_acc}')
    return best_model, best_statistics, best_acc

class Preprocessing:
    def __init__(self, X, y, k, degree=None, categorical=None, method=None):
        """
        Init class
        data: pandas DataFrame, last column represents class labels
        k: int, k-NearestNeighbor are used to impute missing values
        degree: int, do feature engineering --> generate feature with degree less
                     than or equal to specified degree
        """
        if verbose:
            print('Preprocess data')
        self.categorical = categorical
        self.X = X
        self.y = y
        self.k = k
        self.degree = degree
        self.method = method
        
    def clean_data(self):
        """
        Imputes missing values using k nearest neighbors
        return: nxd array, cleaned data
        """
        knn = KNNImputer(n_neighbors=self.k)
        cleaned_data = knn.fit_transform(self.X)
        cleaned_data = pd.DataFrame(cleaned_data, columns=self.X.columns)
        # round numbers thus we can get the correct dummies
        if not self.categorical is None:
            categorical_data = cleaned_data[self.categorical].astype(int)
            cleaned_data.drop(self.categorical, inplace=True, axis=1)
            cleaned_data = pd.concat([cleaned_data, categorical_data], axis=1)
        return cleaned_data
    
    def feature_engineering(self, data):
        """
        Feature engineering, generate polynomial feature with degree less than or equal
        to degree specified.
        return: engineered feature
        """
        poly = PolynomialFeatures(degree=self.degree, include_bias=False)
        data_new = poly.fit_transform(data)
        feature_names = poly.get_feature_names(data.columns)
        return data_new, feature_names

    def check_one_hot_encoding(self, df):
        """
        Perform one hot coding on non-binary, categorical features
        df: pandas DataFrame, nxd with cleaned data
        return: pandas DataFrame with one-hot-encoded categorical features
        """
        for cat in self.categorical:
            # check if binary
            if df[cat].unique().shape[0] == 2:
                continue
            # if not one hot encode
            else:
                if self.method != 'NN':
                    df = pd.get_dummies(df, columns=[cat])
                # drop first column in case of NN --> may lead to disturbances otherwise
                else:
                    df = pd.get_dummies(df, columns=[cat], drop_first=True)
        return df

    def standardize_data(self, df):
        """
        By Elianna Paljug
        Standardizes data with mean and std
        df: pd DataFrame nxd
        return: normalized pandas DataFrame nxd
        """
        sc = StandardScaler()
        df = sc.fit_transform(df)
        return df
    
    def __call__(self):
        """
        Clean data and perform feature engineering if degree is provided
        return: pd DataFrame nxd
        """
        # impute missing values
        cleaned_data = self.clean_data()
        cleaned_data = pd.DataFrame(cleaned_data, columns=self.X.columns)
        # one hot encode categorical features, dissabled for random forest
        if not self.categorical is None and self.method != 'RF':
            cleaned_data = self.check_one_hot_encoding(cleaned_data)
        # standardize data
        preprocessed = self.standardize_data(cleaned_data)
        preprocessed = pd.DataFrame(preprocessed, columns=cleaned_data.columns)
        # do feature engineering
        if not self.degree is None:
            preprocessed, feature_names = self.feature_engineering(preprocessed)
            preprocessed = pd.DataFrame(preprocessed, columns=feature_names)
        return preprocessed

class DimensionalityReduction:
    def __init__(self, data, n_components):
        if verbose:
            print('Perform dimensionality reduction')
        self.data = data
        self.n_components = n_components
    
    def pca(self):
        """
        By Elianna Paljug
        Perform PCA
        return: reduced data with dimensions N x n_components
        """
        pca = PCA(n_components=self.n_components)
        reduced = pca.fit_transform(self.data.values)
        columns = [f'PC{i}' for i in range(1, self.n_components + 1)]
        reduced = pd.DataFrame(reduced, columns=columns)
        return reduced, pca.components_, pca.explained_variance_ratio_

    def __call__(self):
        reduced, components, variance_ratio = self.pca()
        return reduced, components, variance_ratio

class Classification:
    def __init__(self, X, y, method, n_splits, threads):
        if verbose:
            print('Validate and train model')
        self.method = method
        self.n_splits = n_splits
        self.X = X
        self.y = y
        self.threads = threads

    def svc(self):
        """
        Initialize SVC
        """
        svc = SVC(class_weight='balanced', random_state=42, probability=True)
        return svc
    
    def logistic_regression(self):
        """
        Initialize logistic regressor
        """
        lg = LogisticRegression(class_weight='balanced', max_iter=10000,
                                random_state=42, n_jobs=self.threads)
        return lg

    def random_forest(self):
        """
        Initialize Ranfom Forest
        """
        rfc = RandomForestClassifier(class_weight='balanced',
                                     random_state=42, n_jobs=self.threads)
        return rfc

    def define_nn_model(self):
        """
        By Dimitry Shribak
        Define keras model
        return: keras model
        """
        model = Sequential()
        model.add(Dense(25, input_dim=self.X.shape[1], activation='relu'))
        model.add(Dense(15, activation='relu'))
        model.add(Dense(1, activation='sigmoid'))
        return model
    
    def neural_net(self):
        """
        By Dimitry Shribak
        Train simple NN
        return: compiled keras model
        """
        # suppress tensorflow output
        import logging
        logging.getLogger('tensorflow').disabled = True
        # initialize model
        model = self.define_nn_model()
        # compile model
        opt = SGD(lr=0.0001)
        model.compile(loss='binary_crossentropy', optimizer=opt, metrics=['accuracy'])
        return model

    def perform_cv(self, model):
        """
        Evaluate model in cross validation
        model: model
        return: (mean_fpr, mean_tpr, mean_auc)
        """
        # initialize CV
        skf = StratifiedKFold(n_splits=self.n_splits, shuffle=True, random_state=42)
        mean_tpr = 0.0
        mean_fpr = np.linspace(0, 1, 100)
        for train, test in skf.split(self.X, self.y):
            # train model
            if self.method != 'NN':
                model.fit(self.X.values[train, :], self.y.values[train])
                # predict
                probas_ = model.predict_proba(self.X.values[test, :])[:, 1]
            else:
                # train NN
                model.fit(self.X.values[train, :], self.y.values[train], validation_split=0.33,
                          epochs=10, batch_size=10, verbose=0)
                probas_ = model.predict(self.X.values[test, :]).ravel()
            # Compute ROC curve
            fpr, tpr, thresholds = roc_curve(self.y.values[test], probas_)
            mean_tpr += interp(mean_fpr, fpr, tpr)
            mean_tpr[0] = 0.0
            roc_auc = auc(fpr, tpr)
        mean_tpr /= skf.get_n_splits(self.X, self.y)
        mean_tpr[-1] = 1.0
        mean_auc = auc(mean_fpr, mean_tpr)
        if verbose:
            print(f'Mean AUC: {mean_auc}')
        return (mean_fpr, mean_tpr, mean_auc)

    def train_model(self, model):
        """
        Train model on entire training set
        return: trained model
        """
        # train regular model
        if self.method != 'NN':
            model.fit(self.X.values, self.y.values)
        # train neural net
        else:
            # taken from Dimitry Shribak
            model.fit(self.X.values, self.y.values, validation_split=0.33, epochs=40,
                      batch_size=10, verbose=2)
        return model

    def predict(self, X, model):
        """
        Predict class labels of X
        X: test data
        model: trained model
        return: predicted class labels
        """
        if self.method != 'NN':
            return model.predict(X)
        else:
            return model.predict_classes(X)

    def evaluate_model(self, X, y, model):
        """
        Determine accuracy of final model
        """
        ypred = self.predict(X, model)
        acc = accuracy_score(y, ypred)
        if verbose:
            print(f'ACC: {acc}')
        return acc

    def get_best_features(self, model, components, variance_ratio, feature_labels):
        """
        Get the best features of the random Forest
        model: train RF model
        components:n_components x n_features, principal axes in feature space
        variance_ratio: n_components, explained variance ratios
        feature_labels, n_features, actual feature labels
        return: list, best features
        """
        # normalize components n_componets x n_features --> n_feature x n_components
        components = np.absolute(components).T / np.absolute(components).sum(axis=1)        
        # multiply the contribution of each feature to each component by weight of the components
        #  n_feature x n_components --> n_componets x n_feature
        contribution = (components * variance_ratio).T
        # pick most important components
        best_component_inds = np.argsort(model.feature_importances_)[-10:]
        best_components = contribution[best_component_inds, :]
        # sum over all components
        feature_contribution = best_components.sum(axis=0)
        # pick features with greates contribution = best features
        best_feature_inds = np.argsort(feature_contribution)[-10:][::-1]
        best_features = feature_labels[best_feature_inds]
        if verbose:
            print('The top 10 features are:')
            for i, feature in enumerate(best_features):
                print(f'{i + 1}. {feature}')
        return best_features
    
    def __call__(self):
        # initialize model
        if self.method == "SVC":
            model = self.svc()
        elif self.method == 'LR':
            model = self.logistic_regression()
        elif self.method == 'RF':
            model = self.random_forest()
        elif self.method == 'NN':
            model = self.neural_net()
        else:
            raise ValueError("Select one of SVC, LR, RF and NN")
        # cross validate model
        #if self.method != 'NN':
        statistics = self.perform_cv(model)
        # train model on entire training set
        model = self.train_model(model)
        return model, statistics

class Visualization:
    def __init__(self, plot_dir):
        self.plot_dir = plot_dir
        
    def plot_components(self, X_new, y, variance_ratio):
        """
        Plot the first two 2 components
        X_new: Nxn_components PCA transformed data
        return None
        """
        fig, ax = plt.subplots()
        # plot no risk
        ax.scatter(X_new.values[y == 0, 0], X_new.values[y == 0, 1], marker='o', alpha=0.6, c='green', label='No risk')
        # plot risk
        ax.scatter(X_new.values[y == 1, 0], X_new.values[y == 1, 1], marker='x', alpha=0.6, c='red', label='Risk')
        ax.set_xlabel('PC1 {:.1f}%'.format(variance_ratio[0] * 100))
        ax.set_ylabel('PC2 {:.1f}%'.format(variance_ratio[1] * 100))
        ax.set_yscale('symlog')
        ax.set_xscale('symlog')
        ax.legend(bbox_to_anchor=(0.5, -0.13), loc='upper center', ncol=2)
        figname = self.plot_dir + 'pca_transformed.png'
        fig.savefig(figname, bbox_inches='tight')
        
    def plot_roc_curve(self, fpr, tpr, auc):
        """
        Plot ROC curve based on CV results
        fpr: float, mean false positive rate
        tpr: float, mean true positive rate
        auc: float, mean area under curve
        return: None
        """
        fig, ax = plt.subplots()
        # plot fpr vs tpr
        ax.plot(fpr, tpr, label='ROC AUC: {:.2f}'.format(auc))
        ax.plot([0, 1], [0, 1], linestyle='--', color='red')
        # adjust plot settings
        ax.set_xlim([-0.05, 1.05])
        ax.set_ylim([-0.05, 1.05])
        # add labels
        ax.set_xlabel('1 - Specificity')
        ax.set_ylabel('Sensitivity')
        ax.legend(loc='lower right')
        figname = self.plot_dir + 'roc_curve.png'
        fig.savefig(figname, bbox_inches='tight')
        
        
def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', help='Path to data file in .csv format. Column names should be'\
                        'in line 0 and seperator should be ,. Last column contains labels')
    parser.add_argument('-k', type=int, help='k-Nearest-Neighbor are used to impute missing values, default=2', 
                        default=2)
    parser.add_argument('--degree', type=int, help='Generate polynomial features with degree less or equal to specified degree,'\
                        'default=3', default=3)
    parser.add_argument('--n_components', type=int, help='Number of Components used for PCA, default=4', default=4)
    parser.add_argument('--categorical', nargs='+', help='List of categorical features, separated by a space. They will be one-hot-encoded',
                        required=False, default=['education', 'male', 'currentSmoker', 'prevalentStroke', 'prevalentHyp', 'diabetes'])
    parser.add_argument('--n_splits', type=int, help='Number of splits performed during CV, default=10', default=10)
    parser.add_argument('--method', help='Which supervised learning method to use. One of: SVC, LR (LogisticRegression), RF and NN, default=RF', default='RF')
    parser.add_argument('--verbose', help='Verbosity', default=False, action='store_true')
    parser.add_argument('--optimize', help='Perform GridSearch and print optimal settings', default=False, action='store_true')
    parser.add_argument('--output_dir', help='Directory where to save model etc.', default='./output/')
    parser.add_argument('--threads', help='Number of threads to use when possible, default=8', default=8, type=int)
    args = parser.parse_args()
    global verbose
    verbose = args.verbose
    # parse data
    data_df = pd.read_csv(args.data, sep=',', header=0)
    X = data_df.iloc[:, :-1]
    y = data_df.iloc[:, -1]
    visualize = Visualization(args.output_dir)
    # do grid search
    if args.optimize:
        model, statistics, accuracy = perform_gridsearch(X, y, args.categorical, args.threads)
    # run in normal mode
    else:
        # Split data in train and test set   
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
   
        # prepare training data
        preprocessing_train = Preprocessing(X_train, y_train, args.k, args.degree, args.categorical, args.method)
        preprocessed_data_train = preprocessing_train()
        dim_reduction_train = DimensionalityReduction(preprocessed_data_train, args.n_components)
        reduced_data_train, components_train, variance_ratio = dim_reduction_train()
        visualize.plot_components(reduced_data_train, y_train, variance_ratio)
    
        #prepare test data
        preprocessing_test = Preprocessing(X_test, y_test, args.k, args.degree, args.categorical, args.method)
        preprocessed_data_test = preprocessing_test()
        dim_reduction_test= DimensionalityReduction(preprocessed_data_test, args.n_components)
        reduced_data_test, _, _ = dim_reduction_test()

        classification = Classification(reduced_data_train, y_train, args.method, args.n_splits, args.threads)
        model, statistics = classification()
        # if RF get best features --> need model, the fraction with which each feature contributed to component, original feature names
        if args.method == 'RF':
            best_features = classification.get_best_features(model, components_train, variance_ratio,
                                                             preprocessed_data_train.columns)
        
        accuracy = classification.evaluate_model(reduced_data_test, y_test, model)
    if not os.path.isdir(args.output_dir):
        os.makedirs(args.output_dir)
    # plot roc
    visualize.plot_roc_curve(*statistics)
    # save model
    if args.method == 'NN':
        model.save(f'{args.output_dir}trained_model.h5')
    else:
        joblib.dump(model, f'{args.output_dir}trained_model.sav')

if __name__ == '__main__':
    main(sys.argv[1:])
