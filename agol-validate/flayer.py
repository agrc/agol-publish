'''
flayer.py: Lay bare all our feature layers and fix any problems

For each hosted feature layer, check:
    > Tags for malformed spacing, standard AGRC/SGID tags
    > Group & Folder (?) to match source data category
    > Delete Protection enabled
    > Downloads enabled
    > Title against metatable
    > Metadata against SGID (Waiting until 2.5's arcpy metadata tools?)

Also, check the following:
    > Duplicate tags
'''

import arcgis

import getpass
import datetime
import csv
import logging
import pandas as pd


def usage_sum(df):
    '''
    QnD sum of the 'Usage' series in a data frame
    '''
    return df['Usage'].sum()


def item_info(item, folder):
    '''
    Given an item object and a string representing the name of the folder it
    resides in, item_info builds a dictionary containing pertinent info about
    that item.
    '''
    item_dict = {}
    item_dict['itemid'] = item.itemid
    item_dict['title'] = item.title
    item_dict['owner'] = item.owner
    if folder:
        item_dict['folder'] = folder
    else:
        item_dict['folder'] = '_root'
    item_dict['views'] = item.numViews
    item_dict['modified'] = datetime.datetime.fromtimestamp(item.modified/1000).strftime('%Y-%m-%d %H:%M:%S')
    item_dict['authoritative'] = item.content_status
    
    #: Sometimes we get a permission denied error on group listing, so we wrap
    #: it in a try/except to keep moving
    item_dict['open_data'] = 'no'
    try:
        gnames = []
        for g in item.shared_with['groups']:
            gnames.append(g.title)
            if 'Utah SGID' in g.title:
                item_dict['open_data'] = 'yes'
        groups = ', '.join(gnames)
    except:
        groups = 'error'
        item_dict['open_data'] = 'unknown'
    item_dict['groups'] = groups
    
    tag_list = []
    for t in item.tags:
        tag_list.append(t)
    item_dict['tags'] = ', '.join(tag_list)
    mb = item.size/1024/1024
    item_dict['sizeMB'] = mb
    item_dict['credits'] = mb*.24
    
    #: Sometimes data usage also gives an error, so try/except that as well
    try:
        item_dict['data_requests_1Y'] = usage_sum(item.usage('1Y'))
    except:
        item_dict['data_requests_1Y'] = 'error'

    return item_dict


def dict_writer(dictionary, out_path):
    with open(out_path, 'w', newline='') as out_file:
        writer = csv.writer(out_file)
        for key in dictionary:
            row = [key]
            row.extend(dictionary[key])
            writer.writerow(row)


class org:

    #: A dictionary of tags and a list of items that are tagged thus
    #: {tag:[item1, item2, ...]}
    tags_and_items = {}

    #: A list of tags sorted alphabetically
    sorted_tags = []

    #: A list of dictionaries that hold info about each item. As all 
    #: dictionaries from item_info() will have the same keys, this list of
    #: dictionaries can easily be converted to a pandas dataframe.
    feature_services = []

    #: A list of feature service item objects generated by trawling all of 
    #: the user's folders
    feature_service_items = []


    def __init__(self, path, user_name):
        logging.info('==========')
        logging.info('Portal: {}'.format(path))
        logging.info('User: {}'.format(user_name))
        logging.info('==========')

        self.user_name = user_name
        self.gis = arcgis.gis.GIS(path, user_name,
                       getpass.getpass("{}'s password: ".format(user_name)))

        #: Get all the Feature Service item objects in the user's folders
        user_item = self.gis.users.me

        #: Build list of folders. 'None' gives us the root folder.
        print('Getting {}\'s folders...'.format(self.user_name))
        folders = [None]
        for folder in user_item.folders:
            folders.append(folder['title'])

        #: Get info for every item in every folder
        print('Getting item objects...')
        for folder in folders:
            for item in user_item.items(folder, 1000):
                if item.type == 'Feature Service':
                    self.feature_service_items.append(item)


    def get_users_tags_and_item_names(self, method='owner', out_path=None):
        '''
        Populates dictionary of all the tags associated with Feature Services 
        and the name of the Feature Services that are tagged with them, like
        thus: {tag:[item1, item2, ...]}.

        method:     Defines what items are evaluated. 'owner' queries for all
                    Feature Layer items owned by the current owner. 'folder' adds 
                    all Feature Layer items in folders owned by the current owner.
                    These may give different results if other users' data is in 
                    the user's folder. 

        out_path:   if specified, the tag dictionary is sorted by tag name and 
                    then written out as a csv to this path.
        '''

        if method == 'owner':
            items = self.gis.content.search(query='owner:'+self.user_name, 
                                            item_type='Feature Layer', 
                                            max_items=1000)

            #: Create dictionary of tags and a list of items that are tagged thus
            print('Creating list of tags and the items associated with them...')
            for item in items:
                for tag in item.tags:
                    if not tag in self.tags_and_items:
                        self.tags_and_items[tag] = [item.title]
                    else:
                        self.tags_and_items[tag].append(item.title)

        elif method == 'folder':
            for item in self.feature_service_items:
                for tag in item.tags:
                    if not tag in self.tags_and_items:
                        self.tags_and_items[tag] = [item.title]
                    else:
                        self.tags_and_items[tag].append(item.title)


        #: For sanity's sake (this is in sigmund, after all), sort by name
        self.sorted_tags = sorted(self.tags_and_items)

        length_dict = {}
        for key in self.tags_and_items:
            length_dict[key] = [len(self.tags_and_items[key])]
            length_dict[key].extend(sorted(self.tags_and_items[key]))

        if out_path:
            dict_writer(length_dict, out_path)


    def tag_cloud(self, out_path=None):
        '''
        Create a list of all tags in all the items in the user's folders
        (self.feature_services). If out_path is specified, the tags are sorted,
        added to a pandas series, and then written out as an .xls to out_path.
        '''

        tags = []
        for item in self.feature_service_items:
            for tag in item.tags:
                if tag not in tags:
                    tags.append(tag)

        # print(sorted(tags))
        tag_series = pd.Series(sorted(tags))
        print(tag_series)
        if out_path:
            tag_series.to_excel(out_path)


    def get_tags_with_leading_spaces(self, out_path=None):
        '''
        Create a dictionary of items in self.tags_and_items with tags that have
        leading spaces and a list of all their spaced tags:
        {item:[bad_tag1, bad_tag2, ...]}. If out_path is specified, write the
        list as a csv.
        '''

        #: Populate the dictionary of tags and associated items if it is not
        #: already populated.
        if not self.tags_and_items:
            self.get_users_tags_and_item_names()

        print('Saving items with leading-space tags to {}...'.format(out_path))
        leading_space_tagged = {}
        for tag in self.tags_and_items:
            if tag.startswith(' '):
                for item_name in self.tags_and_items[tag]:
                    if item_name not in leading_space_tagged:
                        leading_space_tagged[item_name] = [tag]
                    else:
                        leading_space_tagged[item_name].append(tag)

        if out_path:
            dict_writer(leading_space_tagged, out_path)


    def duplicate_tags(self, out_path=None):

        #: Populate the dictionary of tags and associated items if it is not
        #: already populated.
        if not self.tags_and_items:
            self.get_users_tags_and_item_names()

        #: Dictionary of lower-cased tag and all other tags that match when 
        #: lower-cased
        tags_by_check_tag = {}

        #: For each tag, create a lowercased check_tag version. If check_tag
        #: hasn't been seen before, add it to dictionary of seen tags with value
        #: of 1-element list of the actual tag. If it has been seen (check_tag
        #: is in the dictionary keys), add this new actual tag to the list of
        #: tags associated with the check_tag key. Afterwards, any value (list
        #: of tags) in dictionary with len > 1 indicates functionally duplicate
        #: tags.
        for tag in self.tags_and_items:
            check_tag = tag.lower()

            related_items = [item 
                                for item 
                                in self.tags_and_items[tag]]
            if check_tag in tags_by_check_tag:
                tags_by_check_tag[check_tag].append(related_items)
            else:
                tags_by_check_tag[check_tag] = [related_items]

            dupe_dict = {check_tag : tag_list
                            for check_tag, tag_list
                            in tags_by_check_tag.items()
                            if len(tag_list) > 1}


        if out_path:
            dict_writer(dupe_dict, out_path)


    def tag_fixer(self):
        '''
        Automagically fix tags with spaces, certain capitalized tags, and 
        redundant tags.
        '''

        print('\nEvaluating services\' tags...')
        logging.info('==========')
        logging.info('Fixing tags...')
        failed_group_items = []
        total = len(self.feature_service_items)
        counter = 0
        updated = 0
        for item in self.feature_service_items:
            counter += 1

            orig_tags = [t.strip() for t in item.tags]

            new_tags = []
            for orig_tag in orig_tags:

                #: single-word tag in title
                single_word_tag_not_in_title = True
                if orig_tag in item.title.split():
                    single_word_tag_not_in_title = False
                #: mutli-word tag in title
                multi_word_tag_not_in_title = True
                if ' ' in orig_tag and orig_tag in item.title:
                    multi_word_tag_not_in_title = False

                cleaned_tag = orig_tag.lower()
                #: Upercases: SGID and AGRC
                if cleaned_tag == 'sgid':
                    new_tags.append('SGID')
                elif cleaned_tag == 'agrc':
                    new_tags.append('AGRC')
                #: Fix/keep 'Utah' if it's not in the title
                elif cleaned_tag == 'utah' and orig_tag not in item.title.split():
                    new_tags.append('Utah')
                #: Don't add to new_tags if it should be deleted
                elif cleaned_tag in ['.sd', 'service definition']:
                    pass
                #: Finally, keep the tag unless it's in the title
                elif single_word_tag_not_in_title and multi_word_tag_not_in_title:
                    new_tags.append(orig_tag)
            
            #: Add the category tag
            groups = []
            try:
                for g in item.shared_with['groups']:
                    groups.append(g.title)
            except:
                failed_group_items.append(item.title)

            for group in groups:
                if 'Utah SGID' in group:
                    category = group.split()[-1]
                    #: If there's already a lowercase category tag, replace it
                    if category.lower() in new_tags:
                        new_tags.remove(category.lower())
                        new_tags.append(category)
                    elif category not in new_tags:
                        new_tags.append(category)
                    #: Make sure it's got SGID in it's tags
                    if 'SGID' not in new_tags:
                        new_tags.append('SGID')
            
            #: Only update if the tags have changed
            if sorted(item.tags) != sorted(new_tags):
                #: Update the item
                print('\nUpdating {} ({} of {})'.format(item.title, counter, total))
                print('Old tags: {}'.format(item.tags))
                print('New tags: {}'.format(new_tags))
                logging.info('Old tags <{}>: {}'.format(item.title, item.tags))
                logging.info('New tags <{}>: {}'.format(item.title, new_tags))
                item.update({'tags':new_tags})
                updated += 1
            else:
                print('\nNot updating {} — Tags are the same ({} of {})'.format(item.title, counter, total))
                print('Old tags: {}'.format(item.tags))
                print('New tags: {}'.format(new_tags))
                logging.info('Old tags <{}>: {}'.format(item.title, item.tags))
                logging.info('New tags <{}>: {}'.format(item.title, new_tags))

        print('\nUpdated {} of {} items'.format(updated, total))
        if failed_group_items:
            print('Could not determine group of: {}'.format(failed_group_items))
        logging.info('')
        logging.info('Updated {} of {} items'.format(updated, total))
        if failed_group_items:
            logging.info('Could not determine group of: {}'.format(failed_group_items))
        logging.info('==========')


    def get_feature_services_info(self, out_path=None):
        '''
        Creates a list of dictionaries holding information about each Feature 
        Service in every folder in an AGOL account and saves the list to an
        excel file.
        '''

        print('Creating item information...')
        user_item = self.gis.users.me

        #: Build list of folders. 'None' gives us the root folder.
        folders = [None]
        for folder in user_item.folders:
            folders.append(folder['title'])

        #: Get info for every item in every folder
        for folder in folders:
            for item in user_item.items(folder, 1000):
                if item.type == 'Feature Service':
                    print(item.title)
                    self.feature_services.append(item_info(item, folder))
        
        #: Make a dataframe with properly ordered column names (dictionaries 
        #: are unordered) and then save that as an excel file.
        items_df = pd.DataFrame.from_records(self.feature_services, columns = [
                    'title', 'itemid', 'owner', 'folder', 'groups', 'tags',
                    'authoritative', 'modified', 'views', 'sizeMB', 'credits',
                    'data_requests_1Y', 'open_data'])
        if out_path:
            items_df.to_excel(out_path)


if __name__ == '__main__':
    logfile = r'c:\temp\agol_tag_log.txt'
    # logfile = None
    if logfile:
        logging.basicConfig(filename=logfile, level=logging.INFO)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logging.info('')
    logging.info('Start: {}'.format(now))

    spaces_out = r'c:\temp\agol_spaced.csv'
    items_out = r'c:\temp\agol_layers_postshelf.xls'
    tags_out = r'c:\temp\agol_tags.xls'
    tags_items_out = r'c:\temp\agol_tags_items.csv'
    dupe_tags_out = r'c:\temp\agol_tags_dupes.csv'
    agrc = org('https://www.arcgis.com', 'UtahAGRC')
    # agrc.get_users_tags_and_item_names('folder', tags_out)
    # agrc.get_tags_with_leading_spaces(spaces_out)
    # agrc.get_feature_services_info(items_out)
    # agrc.tag_cloud()
    # agrc.tag_fixer()
    agrc.duplicate_tags(dupe_tags_out)

